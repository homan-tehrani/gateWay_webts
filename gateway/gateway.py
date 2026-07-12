import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from gateway.cache_client import memcache_client
from gateway.container_inspector import get_container_info, resolve_container_name
from gateway.log_builder import (
    build_log_payload,
    is_error_status,
    should_log,
    upstream_host,
)
from gateway.log_publisher import log_publisher
from utils.common import parse_bool
from utils.db import get_route
from utils.global_variables import DO_LOG, LOG_TO_RABBITMQ

logger = logging.getLogger("gateway")

# --------------------------------------------------------------------- #
# Shared upstream HTTP client: ONE pool per worker process.
# Creating an AsyncClient per request forces a new TCP/TLS handshake
# every time -- this pool is the single biggest performance fix.
# --------------------------------------------------------------------- #
UPSTREAM_CLIENT = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
)


async def close_upstream_client() -> None:
    await UPSTREAM_CLIENT.aclose()


class Gateway:
    """
    Single-class API Gateway. One instance per request.
    """

    def __init__(self, request: Request):
        self.request = request
        self.context = None
        self.signature = None
        self.route = None            # upstream base url (path column)
        self.route_info = None       # full row: project_id / project_name / ...
        self.isCache = False
        self.cache_key = None
        self.upstream_url = None
        self._started = time.perf_counter()

    # ------------------------------------------------------------------ #
    # main flow
    # ------------------------------------------------------------------ #
    async def handle_request(self):
        try:
            self.context = await self.extract_request_context()
            self.build_signature()
            await self.resolve_route()

            if self.route is None:
                response = JSONResponse({"detail": "route not found"}, status_code=404)
                self.maybe_log(response, "ROUTE_NOT_FOUND")
                return response

            if not self.isCache:
                response = await self.call_upstream_flow()
                self.maybe_log(response, "UPSTREAM_CALL")
                return response

            self.cache_key = self.build_cache_key()
            cache_result = memcache_client.get(self.cache_key)
            if cache_result:
                response = self.unpack_response(cache_result)
                self.maybe_log(response, "CACHE_HIT")
                return response

            response = await self.call_upstream_flow()

            if self._is_cacheable_response(response):
                memcache_client.set(self.cache_key, self.pack_response(response), time=86400)

            self.maybe_log(response, "CACHE_MISS")
            return response

        except Exception:
            logger.exception("gateway error for %s", getattr(self.request.url, "path", "?"))
            response = JSONResponse({"detail": "gateway error"}, status_code=500)
            self.maybe_log(response, "GATEWAY_EXCEPTION", force=True)
            return response

    async def extract_request_context(self):
        try:
            body = await self.request.body()
        except Exception:
            body = b""

        client = self.request.client
        return {
            "method": self.request.method.upper(),
            "full_url": str(self.request.url),
            "path": self.request.url.path,
            "query": str(self.request.query_params),
            "body": body,
            "headers": dict(self.request.headers),
            "client_ip": client.host if client else None,
        }

    def build_signature(self):
        normalized_path = re.sub(r"/+", "/", self.context["path"]).strip("/")
        parts = [
            "{id}" if segment.isdigit() else segment
            for segment in normalized_path.split("/")
        ]
        self.signature = "/" + "/".join(parts) + "/"

    async def resolve_route(self):
        signature_info = await get_route(self.signature, self.request.method)
        if not signature_info:
            return

        self.route_info = signature_info
        self.route = signature_info.get("path")
        if self.route:
            self.isCache = parse_bool(signature_info.get("cache"))

    # ------------------------------------------------------------------ #
    # cache
    # ------------------------------------------------------------------ #
    def build_cache_key(self):
        parsed_query = parse_qsl(self.context["query"], keep_blank_values=True)
        parsed_query.sort()
        query_hash = hashlib.sha256(urlencode(parsed_query).encode()).hexdigest()
        body_hash = hashlib.sha256(self.context["body"]).hexdigest()
        return f"gw:{self.signature}:{self.context['method']}:{query_hash}:{body_hash}"

    # ------------------------------------------------------------------ #
    # upstream
    # ------------------------------------------------------------------ #
    def build_upstream_request(self):
        url = self.route
        try:
            domain = url.split("/")[2]
            if "log" in domain and url.endswith("/"):
                url = url.rstrip("/")
        except Exception:
            pass

        raw_path_segments = self.context["path"].strip("/").split("/")
        route_segments = re.split(r"/+", self.signature.strip("/"))

        for r_seg, p_seg in zip(route_segments, raw_path_segments):
            if r_seg == "{id}":
                url = url.replace("{id}", p_seg, 1)

        if self.context["query"]:
            url += f"?{self.context['query']}"

        headers = {}
        if "authorization" in self.context["headers"]:
            headers["authorization"] = self.context["headers"]["authorization"]
        if "content-type" in self.context["headers"]:
            headers["content-type"] = self.context["headers"]["content-type"]

        self.upstream_url = url
        return {
            "method": self.context["method"],
            "url": url,
            "headers": headers,
            "body": self.context["body"],
        }

    async def call_upstream(self, upstream_request):
        return await UPSTREAM_CLIENT.request(
            method=upstream_request["method"],
            url=upstream_request["url"],
            headers=upstream_request["headers"],
            content=upstream_request["body"],
        )

    def normalize_upstream_response(self, raw_response):
        if isinstance(raw_response, Response):
            return raw_response
        headers = self._strip_hop_by_hop_headers(dict(raw_response.headers))
        return Response(
            content=raw_response.content,
            status_code=raw_response.status_code,
            headers=headers,
        )

    async def call_upstream_flow(self):
        upstream_request = self.build_upstream_request()
        raw = await self.call_upstream(upstream_request)
        return self.normalize_upstream_response(raw)

    # ------------------------------------------------------------------ #
    # logging -- the ONLY per-request cost for non-matching statuses is
    # the frozenset lookup in should_log().
    # ------------------------------------------------------------------ #
    def maybe_log(self, response: Response, event_type: str, force: bool = False):
        if not DO_LOG or not LOG_TO_RABBITMQ:
            return
        status = response.status_code
        if not force and not should_log(status):
            return

        # Capture everything needed NOW (cheap references), then hand off
        # the payload building + enqueue to a background task.
        task = asyncio.create_task(
            self._build_and_enqueue(response, event_type, status)
        )
        # Keep a strong reference so the task isn't garbage-collected mid-flight.
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _build_and_enqueue(self, response: Response, event_type: str, status: int):
        try:
            duration_ms = (time.perf_counter() - self._started) * 1000

            # Attach container status/logs only for server errors that map
            # to a known container (TTL-cached, executor-backed).
            container_info = None
            if is_error_status(status):
                name = resolve_container_name(
                    (self.route_info or {}).get("project_name"),
                    upstream_host(self.upstream_url),
                )
                if name:
                    container_info = await get_container_info(name)

            payload = build_log_payload(
                context=self.context,
                signature=self.signature,
                route_info=self.route_info,
                upstream_url=self.upstream_url,
                response_status=status,
                response_headers=dict(getattr(response, "headers", {}) or {}),
                response_body=getattr(response, "body", None),
                event_type=event_type,
                duration_ms=duration_ms,
                container_info=container_info,
            )
            log_publisher.enqueue(payload)
        except Exception:
            logger.exception("failed to build log payload")

    # ------------------------------------------------------------------ #
    # response (de)serialization for cache
    # ------------------------------------------------------------------ #
    def pack_response(self, response: Response) -> bytes:
        headers = self._strip_hop_by_hop_headers(
            dict(response.headers) if hasattr(response, "headers") else {}
        )
        payload = {
            "status_code": int(getattr(response, "status_code", 200)),
            "headers": headers,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def unpack_response(self, data: bytes) -> Response:
        try:
            payload = json.loads(data.decode("utf-8"))
            body = base64.b64decode(payload.get("body_b64", ""))
            headers = self._strip_hop_by_hop_headers(payload.get("headers") or {})
            status_code = int(payload.get("status_code", 200))
            return Response(content=body, status_code=status_code, headers=headers)
        except Exception:
            return Response(content=data, status_code=200)

    def _strip_hop_by_hop_headers(self, headers: dict) -> dict:
        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailer",
            "transfer-encoding", "upgrade",
        }
        always_strip = {"content-encoding", "content-length"}

        connection = headers.get("connection") or headers.get("Connection")
        if connection:
            for token in str(connection).split(","):
                name = token.strip().lower()
                if name:
                    hop_by_hop.add(name)

        return {
            k: v for k, v in headers.items()
            if k.lower() not in hop_by_hop and k.lower() not in always_strip
        }

    def _is_cacheable_response(self, response: Response) -> bool:
        if self.context["method"] != "GET":
            return False
        if response.status_code != 200:
            return False
        if "authorization" in self.context["headers"]:
            return False

        headers = dict(getattr(response, "headers", {}))
        if any(k.lower() == "set-cookie" for k in headers.keys()):
            return False

        cc_low = str(
            headers.get("cache-control") or headers.get("Cache-Control") or ""
        ).lower()
        if "no-store" in cc_low or "private" in cc_low or "no-cache" in cc_low:
            return False
        return True


# Strong references for fire-and-forget tasks (asyncio requirement).
_BACKGROUND_TASKS: set[asyncio.Task] = set()
