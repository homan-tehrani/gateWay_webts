"""
Non-blocking RabbitMQ log publishers for the gateway.

Two independent streams share ONE AMQP connection per worker process:

1. DETAILED stream (existing): full request/response payloads for
   matching statuses (errors etc). Low volume, rich payload, published
   one message per event, PERSISTENT.

2. ACCESS stream (new): one tiny record for EVERY request
   (timestamp, method, url, status, duration). High volume, so it is
   batched: records are buffered and published as one NDJSON message
   per ACCESS_BATCH_MAX records or ACCESS_FLUSH_SECONDS, whichever
   comes first. NON_PERSISTENT -- the industry norm for access logs
   (high volume, loss-tolerant), which also keeps broker disk I/O flat.

Hot-path contract (both streams): the request path performs only
capped slices / a small tuple + one ``put_nowait``. All building,
serialization and publishing happens in background workers.

Resource bounds: each stream has its own count cap; the detailed
stream additionally has a byte budget and a per-second rate cap.
Worst-case RAM/CPU spent on logging is a fixed, computable number.

Fail-open everywhere: any publisher failure only loses logs, never
requests.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import aio_pika

try:
    import orjson


    def _dumps(payload) -> bytes:
        return orjson.dumps(payload, default=str)
except ImportError:  # pragma: no cover - stdlib fallback
    import json


    def _dumps(payload) -> bytes:
        return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

from gateway.container_inspector import get_container_info, resolve_container_name
from gateway.log_builder import build_log_payload, is_error_status, upstream_host
from utils.global_variables import (
    ACCESS_BATCH_MAX,
    ACCESS_FLUSH_SECONDS,
    ACCESS_QUEUE_MAXSIZE,
    ACCESS_QUEUE_NAME,
    ACCESS_ROUTING_KEY,
    LOG_MAX_PER_SECOND,
    LOG_QUEUE_MAX_BYTES,
    LOG_QUEUE_MAXSIZE,
    LOG_QUEUE_NAME,
    LOG_ROUTING_KEY,
    RABBIT_AUTO_MIGRATE,
    RABBIT_EXCHANGE_NAME,
    RABBITMQ_HOST,
    RABBITMQ_PASSWORD,
    RABBITMQ_PORT,
    RABBITMQ_USERNAME,
    RABBITMQ_VHOST,
)

logger = logging.getLogger("gateway.log_publisher")


def _item_size(item: dict) -> int:
    """Cheap upper-bound estimate of a detailed item's memory footprint:
    captured body bytes dominate; the rest is small bounded metadata."""
    return len(item["req_body"]) + len(item["resp_body"]) + 1024


class RabbitLogPublisher:
    """Singleton-per-process background publisher (detailed + access)."""

    def __init__(self) -> None:
        # Detailed stream.
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=LOG_QUEUE_MAXSIZE)
        self._queued_bytes = 0
        self._window_start = 0.0
        self._window_count = 0

        # Access stream: fixed-shape tuples -> minimal allocation per request.
        self._access_queue: asyncio.Queue[tuple] = asyncio.Queue(
            maxsize=ACCESS_QUEUE_MAXSIZE
        )

        # Shared AMQP state (one connection, one channel, two exchanges).
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._access_exchange: aio_pika.abc.AbstractExchange | None = None

        self._worker_task: asyncio.Task | None = None
        self._access_task: asyncio.Task | None = None

        # Counters (observability; warnings are rate-limited).
        self._dropped = 0
        self._access_dropped = 0
        self._errors = 0

    # ------------------------------------------------------------------ #
    # lifecycle (called from FastAPI lifespan)
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._run(), name="rabbit-log-worker"
            )
        if self._access_task is None:
            self._access_task = asyncio.create_task(
                self._run_access(), name="rabbit-access-worker"
            )

    async def stop(self) -> None:
        """Graceful shutdown: flush what we can, then close."""
        for q in (self._queue, self._access_queue):
            try:
                await asyncio.wait_for(q.join(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("log queue not fully drained on shutdown")
        for task in (self._worker_task, self._access_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        self._access_task = None
        if self._connection is not None:
            await self._connection.close()

    # ------------------------------------------------------------------ #
    # hot path -- must never block or raise
    # ------------------------------------------------------------------ #
    def enqueue_raw(self, item: dict) -> None:
        """
        Detailed stream. Accept a raw, pre-sliced log item.
        Cost: ~4 arithmetic ops + one put_nowait. No serialization here.
        """
        # Per-second rate limit: caps worker CPU during error storms,
        # exactly when the machine can least afford extra work.
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._window_count = 0
        if self._window_count >= LOG_MAX_PER_SECOND:
            self._drop()
            return
        self._window_count += 1

        # Count + byte budget: worst-case queue RAM is a fixed number.
        if self._queue.full() or self._queued_bytes >= LOG_QUEUE_MAX_BYTES:
            self._drop()
            return

        try:
            self._queue.put_nowait(item)
            self._queued_bytes += _item_size(item)
        except asyncio.QueueFull:
            self._drop()
        except Exception:
            self._errors += 1
            if self._errors % 1000 == 1:  # rate-limited: stack traces are not free
                logger.exception("log enqueue error, total=%d", self._errors)

    def log_access(
            self,
            ts: float,
            method: str,
            url: str,
            status: int,
            duration_ms: float,
            client_ip: str | None,
    ) -> None:
        try:
            self._access_queue.put_nowait(
                (ts, method, url, status, duration_ms, client_ip)
            )
        except asyncio.QueueFull:
            self._access_dropped += 1
            if self._access_dropped % 1000 == 1:
                logger.warning("access log shed, dropped=%d", self._access_dropped)

    def _drop(self) -> None:
        self._dropped += 1
        if self._dropped % 1000 == 1:  # rate-limited warning
            logger.warning("log shed, dropped=%d", self._dropped)

    # ------------------------------------------------------------------ #
    # AMQP topology (shared by both workers)
    # ------------------------------------------------------------------ #
    async def _new_channel(self) -> aio_pika.abc.AbstractChannel:
        return await self._connection.channel(publisher_confirms=False)

    def _reset_amqp(self) -> None:
        self._exchange = None
        self._access_exchange = None
        self._channel = None

    async def _ensure_channel(self) -> None:
        # Reuse the existing channel/exchanges while they are healthy.
        if (
                self._exchange is not None
                and self._access_exchange is not None
                and self._channel is not None
                and not self._channel.is_closed
        ):
            return

        # Close a stale/half-open connection before reconnecting.
        if self._connection is not None and not self._connection.is_closed:
            try:
                await self._connection.close()
            except Exception:
                pass

        self._connection = await aio_pika.connect_robust(
            host=RABBITMQ_HOST,
            port=int(RABBITMQ_PORT or 5672),
            login=RABBITMQ_USERNAME,
            password=RABBITMQ_PASSWORD,
            virtualhost=RABBITMQ_VHOST or "/",
            timeout=10,
        )
        self._channel = await self._new_channel()

        # ---------- detailed exchange: declare durable; self-heal ----------
        try:
            self._exchange = await self._channel.declare_exchange(
                RABBIT_EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT, durable=True,
            )
        except aio_pika.exceptions.ChannelPreconditionFailed:
            # A PRECONDITION_FAILED closes the channel, so open a fresh one.
            self._channel = await self._new_channel()
            if RABBIT_AUTO_MIGRATE:
                # Delete the mismatched exchange and recreate it as durable.
                # Note: bindings of other queues to this exchange are dropped;
                # consumers that declare/bind it themselves must use durable=True.
                await self._channel.exchange_delete(RABBIT_EXCHANGE_NAME)
                self._exchange = await self._channel.declare_exchange(
                    RABBIT_EXCHANGE_NAME, aio_pika.ExchangeType.FANOUT, durable=True,
                )
                logger.warning("migrated exchange '%s' to durable", RABBIT_EXCHANGE_NAME)
            else:
                # Use whatever already exists on the broker.
                self._exchange = await self._channel.get_exchange(RABBIT_EXCHANGE_NAME)

        # ---------- detailed queue: same pattern, delete only if empty ----------
        try:
            queue = await self._channel.declare_queue(LOG_QUEUE_NAME, durable=True)
        except aio_pika.exceptions.ChannelPreconditionFailed:
            self._channel = await self._new_channel()
            self._exchange = await self._channel.get_exchange(RABBIT_EXCHANGE_NAME)
            migrated = False
            if RABBIT_AUTO_MIGRATE:
                try:
                    # if_empty=True: the delete fails (does nothing) if the
                    # queue still holds messages, so we never lose logs.
                    await self._channel.queue_delete(LOG_QUEUE_NAME, if_empty=True)
                    queue = await self._channel.declare_queue(LOG_QUEUE_NAME, durable=True)
                    logger.warning("migrated queue '%s' to durable", LOG_QUEUE_NAME)
                    migrated = True
                except Exception:
                    # Queue is non-empty or delete failed; the channel is now
                    # closed, so reopen it and fall back to the existing queue.
                    self._channel = await self._new_channel()
                    self._exchange = await self._channel.get_exchange(RABBIT_EXCHANGE_NAME)
            if not migrated:
                queue = await self._channel.declare_queue(LOG_QUEUE_NAME, passive=True)

        await queue.bind(self._exchange, routing_key=LOG_ROUTING_KEY)

        # ---------- access exchange + queue (own fanout, own queue) ----------
        # Access records are transient; the queue itself is durable so the
        # topology survives broker restarts, but messages are NON_PERSISTENT.
        self._access_exchange = await self._channel.declare_exchange(
            f"{RABBIT_EXCHANGE_NAME}.access", aio_pika.ExchangeType.FANOUT, durable=True,
        )
        access_queue = await self._channel.declare_queue(
            ACCESS_QUEUE_NAME,
            durable=True,
            arguments={
                # Broker-side safety net: cap the queue so a slow/absent
                # consumer can never grow broker RAM/disk unboundedly.
                "x-max-length-bytes": 64 * 1024 * 1024,
                "x-overflow": "drop-head",
            },
        )
        await access_queue.bind(self._access_exchange, routing_key=ACCESS_ROUTING_KEY)

        logger.info(
            "rabbit ready: exchange=%s queue=%s access_queue=%s",
            RABBIT_EXCHANGE_NAME, LOG_QUEUE_NAME, ACCESS_QUEUE_NAME,
        )

    # ------------------------------------------------------------------ #
    # detailed worker -- all expensive work lives here
    # ------------------------------------------------------------------ #
    async def _process(self, item: dict) -> None:
        """Build + serialize + publish one detailed log item."""
        # Attach container status only for server errors that map to a
        # known container. Running here (serially) means an error storm
        # triggers at most one inspection at a time, backed by TTL cache.
        if is_error_status(item["status"]) and item.get("container") is None:
            name = resolve_container_name(
                (item["route_info"] or {}).get("project_name"),
                upstream_host(item["upstream_url"]),
            )
            if name:
                item["container"] = await get_container_info(name)

        payload = build_log_payload(item)
        body = _dumps(payload)

        await self._ensure_channel()
        await self._exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=LOG_ROUTING_KEY,
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            self._queued_bytes -= _item_size(item)
            try:
                await self._process(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail-open: drop this message, reset AMQP state, back off
                # briefly so a dead broker doesn't spin the CPU.
                self._errors += 1
                if self._errors % 100 == 1:
                    logger.exception("failed to publish log message (dropped)")
                self._reset_amqp()
                await asyncio.sleep(1)
            finally:
                self._queue.task_done()
                # Yield to the event loop so a long drain never starves
                # request handling on a resource-constrained machine.
                await asyncio.sleep(0)

    # ------------------------------------------------------------------ #
    # access worker -- batched NDJSON publishing
    # ------------------------------------------------------------------ #
    def _render_access_batch(self, batch: list[tuple]) -> bytes:
        lines = []
        for ts, method, url, status, duration_ms, client_ip in batch:
            lines.append(_dumps({
                "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "method": method,
                "url": url,
                "status": status,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
            }))
        return b"\n".join(lines)

    async def _flush_access(self, batch: list[tuple]) -> None:
        if not batch:
            return
        body = self._render_access_batch(batch)
        await self._ensure_channel()
        await self._access_exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/x-ndjson",
                delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT,
                headers={"record_count": len(batch)},
            ),
            routing_key=ACCESS_ROUTING_KEY,
        )

    async def _run_access(self) -> None:
        """
        Collect access records and flush as one message per
        ACCESS_BATCH_MAX records or ACCESS_FLUSH_SECONDS -- whichever
        comes first. Batching turns thousands of per-request publishes
        into a handful per second: the single biggest cost reduction
        for an every-request log stream.
        """
        batch: list[tuple] = []
        while True:
            try:
                # Block indefinitely when idle; once the batch is non-empty,
                # wait at most the flush interval for more records.
                timeout = ACCESS_FLUSH_SECONDS if batch else None
                item = await asyncio.wait_for(self._access_queue.get(), timeout)
                batch.append(item)
                self._access_queue.task_done()
                if len(batch) < ACCESS_BATCH_MAX:
                    continue
            except asyncio.TimeoutError:
                pass  # interval elapsed -> flush whatever we have
            except asyncio.CancelledError:
                # Best-effort final flush on shutdown.
                try:
                    await self._flush_access(batch)
                except Exception:
                    pass
                raise

            try:
                await self._flush_access(batch)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._errors += 1
                if self._errors % 100 == 1:
                    logger.exception("failed to publish access batch (dropped)")
                self._reset_amqp()
                await asyncio.sleep(1)
            finally:
                batch = []


# One instance per worker process.
log_publisher = RabbitLogPublisher()
