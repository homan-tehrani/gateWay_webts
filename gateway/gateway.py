import asyncio
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from gateway.cache_client import cache
from utils.db import get_url
from utils.common import send_log_to_rabbitmq
from utils.cache_keys import (
    normalize_signature,
    route_version_key,
    route_data_key,
    response_key,
    get_or_init_version
)
from utils.cache_response import pack_response, unpack_response


class GateWay:

    def __init__(self, request: Request):
        self.request = request
        self.method = request.method.upper()
        self.token = request.headers.get("authorization")
        self.db_url = None

    async def handle(self):
        try:
            route = await self._get_route()
            if not route:
                return JSONResponse({"detail": "address not found"}, status_code=404)

            response = await self._call_upstream(route)
            return response

        except Exception as e:
            print(e)
            asyncio.create_task(
                send_log_to_rabbitmq(self.request, 1, str(e), 500, self.db_url)
            )
            return JSONResponse({"detail": "gateway error"}, status_code=500)

    async def _get_route(self):
        signature = normalize_signature(self.request.url.path)
        ver_key = route_version_key(signature)
        version = get_or_init_version(cache, ver_key)

        rkey = route_data_key(signature, version)
        cached = cache.get(rkey)
        if cached:
            self.db_url = cached
            return cached

        url = await get_url(signature)
        if not url:
            return None

        if url["method"].lower() != self.method.lower():
            return None

        cache.set(rkey, url)
        self.db_url = url
        return url

    async def _call_upstream(self, route):
        if route["cache"] == 0:
            return await self._direct_call(route)

        signature = normalize_signature(self.request.url.path)
        version = get_or_init_version(cache, route_version_key(signature))

        body = await self.request.body()
        query = str(self.request.query_params)

        rkey = response_key(signature, version, self.method, query, body)
        cached = cache.get(rkey)
        if cached:
            return unpack_response(cached)

        resp = await self._direct_call(route)

        if resp.status_code == 200:
            cache.set(rkey, pack_response(resp))

        return resp

    async def _direct_call(self, route):
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        if self.request.headers.get("content-type"):
            headers["Content-Type"] = self.request.headers["content-type"]

        url = route["path"]
        if self.request.query_params:
            url += f"?{self.request.query_params}"

        body = await self.request.body()

        async with httpx.AsyncClient(timeout=30) as client:
            if self.method == "GET":
                upstream = await client.get(url, headers=headers)
            elif self.method == "POST":
                upstream = await client.post(url, headers=headers, data=body)
            elif self.method == "PUT":
                upstream = await client.put(url, headers=headers, data=body)
            elif self.method == "DELETE":
                upstream = await client.delete(url, headers=headers, data=body)
            else:
                return JSONResponse(
                    content={"detail": "method not allowed"},
                    status_code=405
                )

        # Try to parse JSON safely
        try:
            data = upstream.json()
        except Exception:
            return JSONResponse(
                content={
                    "detail": "upstream response is not valid JSON",
                    "status_code": upstream.status_code
                },
                status_code=502
            )

        return JSONResponse(
            content=data,
            status_code=upstream.status_code
        )
