"""
Non-blocking RabbitMQ log publisher for the gateway.

Design goals (in priority order):
1. Zero added latency on the request path: enqueue is a lock-free
   ``put_nowait`` on an in-memory asyncio.Queue. If the queue is full,
   the log is dropped -- backpressure never reaches the client.
2. One persistent AMQP connection/channel per worker process
   (aio_pika RobustConnection reconnects automatically). No
   per-message connections, no per-message event loops, no threads.
3. Fail-open: any publisher failure only loses logs, never requests.
"""

import asyncio
import json
import logging

import aio_pika

from utils.global_variables import (
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


class RabbitLogPublisher:
    """Singleton-per-process background publisher."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=LOG_QUEUE_MAXSIZE)
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._worker_task: asyncio.Task | None = None
        self._dropped = 0  # counter for observability

    # ------------------------------------------------------------------ #
    # lifecycle (called from FastAPI lifespan)
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._run(), name="rabbit-log-worker")

    async def stop(self) -> None:
        """Graceful shutdown: flush what we can, then close."""
        if self._worker_task is None:
            return
        try:
            # Give the worker a short window to drain the queue.
            await asyncio.wait_for(self._queue.join(), timeout=5)
        except asyncio.TimeoutError:
            logger.warning("log queue not fully drained on shutdown")
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        if self._connection is not None:
            await self._connection.close()
        self._worker_task = None

    # ------------------------------------------------------------------ #
    # hot path -- called per matching request, must never block or raise
    # ------------------------------------------------------------------ #
    def enqueue(self, payload: dict) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._queue.put_nowait(body)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 1000 == 1:  # rate-limited warning
                logger.warning("log queue full, dropped=%d", self._dropped)
        except Exception:
            logger.exception("failed to enqueue log payload")

    # ------------------------------------------------------------------ #
    # background worker
    # ------------------------------------------------------------------ #
    async def _new_channel(self) -> aio_pika.abc.AbstractChannel:
        return await self._connection.channel(publisher_confirms=False)

    async def _ensure_channel(self) -> None:
        # Reuse the existing channel/exchange while they are healthy.
        if (
            self._exchange is not None
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

        # ---------- exchange: declare durable; self-heal on mismatch ----------
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

        # ---------- queue: same pattern, but delete only if empty ----------
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

        # For a fanout exchange the routing key is ignored, but we keep it
        # for compatibility with any topic/direct reconfiguration later.
        await queue.bind(self._exchange, routing_key=LOG_ROUTING_KEY)
        logger.info("rabbit ready: exchange=%s queue=%s", RABBIT_EXCHANGE_NAME, LOG_QUEUE_NAME)

    async def _run(self) -> None:
        while True:
            body = await self._queue.get()
            try:
                await self._ensure_channel()
                await self._exchange.publish(
                    aio_pika.Message(
                        body=body,
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key=LOG_ROUTING_KEY,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail-open: drop this message, reset state, back off briefly
                # so a dead broker doesn't spin the CPU.
                logger.exception("failed to publish log message (dropped)")
                self._exchange = None
                self._channel = None
                await asyncio.sleep(1)
            finally:
                self._queue.task_done()


# One instance per worker process.
log_publisher = RabbitLogPublisher()
