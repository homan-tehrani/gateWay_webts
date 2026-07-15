import base64
import hashlib
import json
import logging
import time
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from gateway.cache_client import memcache_client
from gateway.log_builder import capture_body, should_log
from gateway.log_publisher import log_publisher
from utils.common import parse_bool
from utils.db import get_route
from utils.global_variables import (
    ACCESS_LOG_ENABLED,
    CACHE_MAX_BODY_BYTES,
    DO_LOG,
    LOG_TO_RABBITMQ,
)

logger = logging.getLogger("gateway")

# Both flags are set once at startup; collapse them into one boolean so
# the per-request check is a single name lookup.
LOGGING_ENABLED = DO_LOG and LOG_TO_RABBITMQ

# Shared upstream HTTP client: one pool per worker process.
UPSTREAM_CLIENT = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
)

# Module-level frozensets: built once, not per call.
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
_ALWAYS_STRIP = frozenset({"content-encoding", "content-length"})


async def close_upstream_client() -> None:
    await UPSTREAM_CLIENT.aclose()


def _normalize_log_domain_trailing_slash(url: str | None) -> str | None:
    if not url:
        return url

    try:
        domain = url.split("/")[2]
        if "log" in domain and url.endswith("/"):
            return url.rstrip("/")
    except Exception:
        pass

    return url


class Gateway:
    """
    Single-class API Gateway. One instance per request.

    Logging contract: for non-matching statuses the only logging cost is
    one frozenset lookup. For matching statuses the request path pays a
    few bounded slices plus one put_nowait; everything expensive happens
    in the publisher worker.
    """

    def __init__(self, request: Request):
        self.request = request
        self.context = None
        self.signature = None
        self.route = None
        self.route_info = None
        self.isCache = False
        self.cache_key = None
        self.upstream_url = None
        self._started = time.perf_counter()

    async def handle_request(self):
        response = None
        try:
            response = await self._dispatch()
            return response
        except Exception:
            logger.exception(
                "gateway error for %s",
                getattr(self.request.url, "path", "?"),
            )
            response = JSONResponse({"detail": "gateway error"}, status_code=500)
            self.maybe_log(response, "GATEWAY_EXCEPTION", force=True)
            return response
        finally:
            if ACCESS_LOG_ENABLED and response is not None:
                ctx = self.context or {}
                log_publisher.log_access(
                    ts=time.time(),
                    method=ctx.get("method") or self.request.method,
                    url=_normalize_log_domain_trailing_slash(
                        ctx.get("full_url") or str(self.request.url)
                    ),
                    status=response.status_code,
                    duration_ms=(time.perf_counter() - self._started) * 1000,
                    client_ip=ctx.get("client_ip"),
                )

    async def _dispatch(self):
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
            if response is not None:
                self.maybe_log(response, "CACHE_HIT")
                return response
            # Corrupt cache entry: treat as a miss and fall through.

        response = await self.call_upstream_flow()

        if self._is_cacheable_response(response):
            memcache_client.set(
                self.cache_key,
                self.pack_response(response),
                time=86400,
            )

        self.maybe_log(response, "CACHE_MISS")
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
        parts = [
            "{id}" if segment.isdigit() else segment
            for segment in self.context["path"].split("/")
            if segment
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

    def build_cache_key(self):
        parsed_query = parse_qsl(self.context["query"], keep_blank_values=True)
        parsed_query.sort()
        query_hash = hashlib.sha256(urlencode(parsed_query).encode()).hexdigest()
        body_hash = hashlib.sha256(self.context["body"]).hexdigest()
        return f"gw:{self.signature}:{self.context['method']}:{query_hash}:{body_hash}"

    def build_upstream_request(self):
        url = _normalize_log_domain_trailing_slash(self.route)

        raw_path_segments = self.context["path"].strip("/").split("/")
        route_segments = self.signature.strip("/").split("/")

        for r_seg, p_seg in zip(route_segments, raw_path_segments):
            if r_seg == "{id}":
                url = url.replace("{id}", p_seg, 1)

        if self.context["query"]:
            url += f"?{self.context['query']}"

        headers = {}
        req_headers = self.context["headers"]
        if "authorization" in req_headers:
            headers["authorization"] = req_headers["authorization"]
        if "content-type" in req_headers:
            headers["content-type"] = req_headers["content-type"]

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

    def maybe_log(self, response: Response, event_type: str, force: bool = False):
        if not LOGGING_ENABLED:
            return

        status = response.status_code
        if not force and not should_log(status):
            return

        try:
            ctx = self.context or {}
            req_headers = ctx.get("headers") or {}
            resp_headers = dict(getattr(response, "headers", {}) or {})
            resp_bytes = getattr(response, "body", b"") or b""

            req_body, req_trunc, req_note = capture_body(
                ctx.get("body"),
                req_headers.get("content-type"),
            )
            resp_body, resp_trunc, resp_note = capture_body(
                resp_bytes,
                resp_headers.get("content-type"),
            )

            full_url = _normalize_log_domain_trailing_slash(ctx.get("full_url"))

            log_publisher.enqueue_raw({
                "ts": time.time(),
                "event_type": event_type,
                "status": status,
                "duration_ms": (time.perf_counter() - self._started) * 1000,
                "method": ctx.get("method"),
                "full_url": full_url,
                "path": ctx.get("path"),
                "query": ctx.get("query"),
                "client_ip": ctx.get("client_ip"),
                "req_headers": req_headers,
                "req_body": req_body,
                "req_trunc": req_trunc,
                "req_note": req_note,
                "resp_headers": resp_headers,
                "resp_body": resp_body,
                "resp_trunc": resp_trunc,
                "resp_note": resp_note,
                "signature": self.signature,
                "upstream_url": self.upstream_url,
                "route_info": self.route_info,
                "container": None,
            })
        except Exception:
            logger.exception("maybe_log failed")

    def pack_response(self, response: Response) -> bytes:
        headers = self._strip_hop_by_hop_headers(dict(response.headers))
        payload = {
            "status_code": int(getattr(response, "status_code", 200)),
            "headers": headers,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def unpack_response(self, data: bytes) -> Response | None:
        """Return the cached response, or None if the entry is corrupt."""
        try:
            payload = json.loads(data.decode("utf-8"))
            body = base64.b64decode(payload.get("body_b64", ""))
            headers = self._strip_hop_by_hop_headers(payload.get("headers") or {})
            status_code = int(payload.get("status_code", 200))
            return Response(content=body, status_code=status_code, headers=headers)
        except Exception:
            return None

    def _strip_hop_by_hop_headers(self, headers: dict) -> dict:
        drop = _HOP_BY_HOP
        connection = headers.get("connection")
        if connection:
            drop = set(_HOP_BY_HOP)
            for token in str(connection).split(","):
                name = token.strip().lower()
                if name:
                    drop.add(name)

        return {
            k: v
            for k, v in headers.items()
            if k.lower() not in drop and k.lower() not in _ALWAYS_STRIP
        }

    def _is_cacheable_response(self, response: Response) -> bool:
        if self.context["method"] != "GET":
            return False
        if response.status_code != 200:
            return False
        if "authorization" in self.context["headers"]:
            return False

        body = getattr(response, "body", b"") or b""
        if len(body) > CACHE_MAX_BODY_BYTES:
            return False

        headers = response.headers
        if "set-cookie" in headers:
            return False

        cc = (headers.get("cache-control") or "").lower()
        if "no-store" in cc or "private" in cc or "no-cache" in cc:
            return False

        return True
