import asyncio
import hashlib
import re
import sentry_sdk

from datetime import datetime
from urllib.parse import parse_qsl, urlencode
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from utils.global_variables import DO_LOG, LOG_TO_RABBITMQ, LOG_TO_SENTRY
from gateway.cache_client import memcache_client
from utils.common import send_log_to_rabbitmq
from utils.db import get_route


LOG_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="gateway-log"
)


class Gateway:
    """
    Single-class API Gateway.
    One instance per request.
    """

    def __init__(self, request: Request):
        self.request = request

        self.context = None
        self.signature = None
        self.route = None
        self.isCache = False
        self.cache_key = None

    async def handle_request(self):
        try:
            self.context = await self.extract_request_context()
            print(self.context, 11111111111111)

            self.build_signature()
            print(self.signature, 22222222)

            await self.resolve_route()
            print(self.route, self.isCache, 333333333)

            if self.route is None:
                response = JSONResponse({"detail": "route not found"}, status_code=404)
                self.fire_and_forget_log(response, "ROUTE_NOT_FOUND")
                return response

            if not self.isCache:
                response = await self.call_upstream_flow()
                self.fire_and_forget_log(response, "UPSTREAM_CALL")
                return response

            self.cache_key = self.build_cache_key()
            print(self.cache_key, 8888888888)

            cache_result = memcache_client.get(self.cache_key)

            if cache_result:
                response = self.unpack_response(cache_result)
                self.fire_and_forget_log(response, "CACHE_HIT")
                return response

            response = await self.call_upstream_flow()

            if response.status_code == 200:
                memcache_client.set(self.cache_key, self.pack_response(response))

            self.fire_and_forget_log(response, "CACHE_MISS")
            return response

        except Exception:
            response = JSONResponse({"detail": "gateway error"}, status_code=500)
            self.fire_and_forget_log(response, "GATEWAY_EXCEPTION", force=True)
            return response

    async def extract_request_context(self):
        try:
            body = await self.request.body()
        except Exception:
            body = b""

        return {
            "method": self.request.method.upper(),
            "full_url": str(self.request.url),
            "path": self.request.url.path,
            "query": str(self.request.query_params),
            "body": body,
            "headers": dict(self.request.headers),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def build_signature(self):
        raw_path = self.context["path"]

        normalized_path = re.sub(r"/+", "/", raw_path).strip("/")

        parts = []
        for segment in normalized_path.split("/"):
            if segment.isdigit():
                parts.append("{id}")
            else:
                parts.append(segment)

        self.signature = "/" + "/".join(parts) + "/"

    async def resolve_route(self):
        signature_info = await get_route(self.signature, self.request.method)
        if not signature_info:
            return

        self.route = signature_info.get("path")
        if self.route:
            self.isCache = signature_info.get("cache") == 1

    def build_cache_key(self):
        parsed_query = parse_qsl(self.context["query"], keep_blank_values=True)
        parsed_query.sort()

        query_hash = hashlib.sha256(
            urlencode(parsed_query).encode()
        ).hexdigest()

        body_hash = hashlib.sha256(self.context["body"]).hexdigest()

        return f"gw:{self.signature}:{self.context['method']}:{query_hash}:{body_hash}"

    def build_upstream_request(self):
        url = self.route
        if self.context["query"]:
            url += f"?{self.context['query']}"

        headers = {}

        if "authorization" in self.context["headers"]:
            headers["authorization"] = self.context["headers"]["authorization"]

        if "content-type" in self.context["headers"]:
            headers["content-type"] = self.context["headers"]["content-type"]

        return {
            "method": self.context["method"],
            "url": url,
            "headers": headers,
            "body": self.context["body"],
        }

    async def call_upstream(self, upstream_request):
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.request(
                method=upstream_request["method"].lower(),
                url=upstream_request["url"],
                headers=upstream_request["headers"],
                content=upstream_request["body"],
            )

    def normalize_upstream_response(self, raw_response):
        if isinstance(raw_response, Response):
            return raw_response

        return Response(
            content=raw_response.content,
            status_code=raw_response.status_code,
            headers={
                "content-type": raw_response.headers.get("content-type", "")
            },
        )

    async def call_upstream_flow(self):
        upstream_request = self.build_upstream_request()
        print(upstream_request, 66666666666)

        raw = await self.call_upstream(upstream_request)
        print(raw, 7777777777)

        return self.normalize_upstream_response(raw)

    def fire_and_forget_log(self, response, event_type, force=False):
        payload = self.build_log_payload(response, event_type)
        print(payload, 55555555)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            LOG_EXECUTOR,
            self._thread_dispatch_log,
            payload,
            response.status_code,
            force
        )

    def build_log_payload(self, response, event_type):
        return {
            "signature": self.signature,
            "isCache": self.isCache,
            "full_url": self.context["full_url"],
            "method": self.context["method"],
            "request_body": self.context["body"].decode(errors="ignore"),
            "response_body": response.body.decode(errors="ignore")
            if hasattr(response, "body") else "",
            "status_code": response.status_code,
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _thread_dispatch_log(self, payload, status_code, force):
        if not force:
            if DO_LOG == 0:
                return
            if DO_LOG == 2 and status_code < 500:
                return

        try:
            if LOG_TO_RABBITMQ:
                asyncio.run(send_log_to_rabbitmq(payload))

            if LOG_TO_SENTRY:
                sentry_sdk.capture_message(str(payload))

        except Exception:
            pass

    def pack_response(self, response: Response) -> bytes:
        return response.body

    def unpack_response(self, data: bytes) -> Response:
        return Response(content=data, status_code=200)
