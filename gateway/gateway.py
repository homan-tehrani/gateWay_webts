import asyncio
import base64
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qsl, urlencode

import httpx
import sentry_sdk
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from gateway.cache_client import memcache_client
from utils.common import send_log_to_rabbitmq,parse_bool
from utils.db import get_route
from utils.global_variables import DO_LOG, LOG_TO_RABBITMQ, LOG_TO_SENTRY

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
            # print(self.context, 11111111111111)

            self.build_signature()
            # print(self.signature, 22222222)

            await self.resolve_route()
            # print(self.route, self.isCache, 333333333)

            if self.route is None:
                response = JSONResponse({"detail": "route not found"}, status_code=404)
                self.fire_and_forget_log(response, "ROUTE_NOT_FOUND")
                return response

            if not self.isCache:
                response = await self.call_upstream_flow()
                self.fire_and_forget_log(response, "UPSTREAM_CALL")
                return response

            self.cache_key = self.build_cache_key()
            # print(self.cache_key, 8888888888)

            cache_result = memcache_client.get(self.cache_key)
            print(cache_result,999999999999)
            if cache_result:
                response = self.unpack_response(cache_result)
                self.fire_and_forget_log(response, "CACHE_HIT")
                return response

            response = await self.call_upstream_flow()

            if self._is_cacheable_response(response):
                memcache_client.set(self.cache_key, self.pack_response(response), time=86400)

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
        print("RAW PATH:", self.context["path"])

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

        print("ROUTE INFO:", signature_info)

        self.route = signature_info.get("path")

        if self.route:
            cache_val = signature_info.get("cache")
            self.isCache = parse_bool(cache_val)

            print("CACHE RAW:", cache_val)
            print("ISCACHE:", self.isCache)

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
        try:
            domain = url.split("/")[2]
            if "log" in domain and url.endswith("/"):
                url = url.rstrip("/")
        except Exception:
            pass

        # --- 🔍 Replace dynamic path segments like {id} with real values from request ---
        raw_path_segments = self.context["path"].strip("/").split("/")
        route_segments = re.split(r"/+", self.signature.strip("/"))

        replacements = {}
        # create a map like {"{id}": "2499"}
        for r_seg, p_seg in zip(route_segments, raw_path_segments):
            if r_seg == "{id}":
                replacements["{id}"] = p_seg

        # replace placeholders in final URL
        for placeholder, val in replacements.items():
            url = url.replace(placeholder, val)

        # --- keep query params if any ---
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
        async with httpx.AsyncClient(timeout=12000) as client:
            return await client.request(
                method=upstream_request["method"].lower(),
                url=upstream_request["url"],
                headers=upstream_request["headers"],
                content=upstream_request["body"],
            )

    def normalize_upstream_response(self, raw_response):
        if isinstance(raw_response, Response):
            return raw_response

        headers = dict(raw_response.headers)
        headers = self._strip_hop_by_hop_headers(headers)

        return Response(
            content=raw_response.content,
            status_code=raw_response.status_code,
            headers=headers,
        )

    async def call_upstream_flow(self):
        upstream_request = self.build_upstream_request()
        # print(upstream_request, 66666666666)

        raw = await self.call_upstream(upstream_request)
        # print(raw, 7777777777)

        return self.normalize_upstream_response(raw)

    def fire_and_forget_log(self, response, event_type, force=False):
        payload = self.build_log_payload(response, event_type)
        # print(payload, 55555555)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            LOG_EXECUTOR,
            self._thread_dispatch_log,
            payload,
            response.status_code,
            force
        )

    def build_log_payload(self, response, event_type):
        full_url = self.context["full_url"]

        # If the domain contains "log" and ends with "/", remove the trailing slash
        if "log" in full_url.split("/")[2] and full_url.endswith("/"):
            full_url = full_url.rstrip("/")
        return {
            "signature": self.signature,
            "isCache": self.isCache,
            "full_url": full_url,
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
        headers = dict(response.headers) if hasattr(response, "headers") else {}
        headers = self._strip_hop_by_hop_headers(headers)

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
            headers = payload.get("headers") or {}
            headers = self._strip_hop_by_hop_headers(headers)
            status_code = int(payload.get("status_code", 200))
            return Response(content=body, status_code=status_code, headers=headers)
        except Exception:
            return Response(content=data, status_code=200)

    def _strip_hop_by_hop_headers(self, headers: dict) -> dict:
        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }

        # Also strip headers that become invalid after httpx decompression / rewriting
        always_strip = {
            "content-encoding",
            "content-length",
        }

        connection = headers.get("connection") or headers.get("Connection")
        if connection:
            for token in str(connection).split(","):
                name = token.strip().lower()
                if name:
                    hop_by_hop.add(name)

        cleaned = {}
        for k, v in headers.items():
            lk = k.lower()
            if lk in hop_by_hop:
                continue
            if lk in always_strip:
                continue
            cleaned[k] = v

        return cleaned

    def _is_cacheable_response(self, response: Response) -> bool:
        if self.context["method"] != "GET":
            return False

        if response.status_code != 200:
            return False

        headers = dict(getattr(response, "headers", {}))
        if "authorization" in self.context["headers"]:
            return False

        # Do not cache responses that vary by request headers (simple performance mode)
        # vary = headers.get("vary") or headers.get("Vary") or ""
        # if str(vary).strip():
        #     return False

        # Never cache responses that set cookies (risk of leakage)
        if any(k.lower() == "set-cookie" for k in headers.keys()):
            return False

        cache_control = headers.get("cache-control") or headers.get("Cache-Control") or ""
        cc_low = str(cache_control).lower()

        if "no-store" in cc_low:
            return False
        if "private" in cc_low:
            return False
        if "no-cache" in cc_low:
            return False

        return True

