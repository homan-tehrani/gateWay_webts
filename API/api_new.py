import os
import time
from datetime import datetime

import docker
import psutil
from API.urlSchema import AddUrlValidation, AddListUrlValidation, DeleteUrlValidation
from dotenv import load_dotenv
from fastapi import APIRouter, Body, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from gateway.cache_client import memcache_client as cache
from pydantic import ValidationError
from utils.db import (
    get_url,
    get_urls,
    delete_url,
    update_Url,
    create_Url,
    check_url_table_exists,
)

router = APIRouter(prefix="/url")
load_dotenv()


def _auth_or_401(authorization: str | None):
    # Validate admin token
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است.")


def _normalize_signature(sig: str) -> str:
    # Normalize signature to always end with '/'
    if not sig:
        return sig
    return sig if sig.endswith("/") else sig + "/"


def _route_version_key(signature: str) -> str:
    # Namespace for route version keys
    return f"ver:route:{signature}"


def _ensure_version_exists(signature: str) -> int:
    # Memcached incr needs an existing numeric key
    k = _route_version_key(signature)
    v = cache.get(k)
    if v is None:
        cache.add(k, 1)
        return 1
    try:
        return int(v)
    except Exception:
        cache.set(k, 1)
        return 1


def _bump_route_version(signature: str) -> int:
    # Invalidate only one route by bumping its version
    k = _route_version_key(signature)
    v = cache.get(k)
    if v is None:
        cache.add(k, 1)
        return 1
    try:
        return int(cache.incr(k, 1))
    except Exception:
        # Fallback if incr is not supported by client or key is corrupted
        new_v = int(time.time())
        cache.set(k, new_v)
        return new_v


@router.post("/addUrl/")
async def add_url(datas: AddListUrlValidation = Body(), authorization: str = Header(None)):
    _auth_or_401(authorization)
    await check_url_table_exists()

    try:
        changed_signatures: set[str] = set()
        skipped_cache: list[str] = []

        for raw in datas.data:
            # Validate payload item
            try:
                data = AddUrlValidation(**raw)
            except ValidationError as e:
                return JSONResponse(content={"detail": str(e)}, status_code=400)

            # Normalize signature
            sig = _normalize_signature(data.signature)

            # Check if signature is safe for cache
            try:
                sig.encode("ascii")
                cache_safe = (" " not in sig)
            except UnicodeEncodeError:
                cache_safe = False

            # Force cache off for unsafe signatures
            if not cache_safe:
                data.cache = 0
                skipped_cache.append(sig)

            # Check by id
            existing = await get_url(data.id)

            if existing:
                await update_Url(
                    data.id,
                    data.path,
                    sig,
                    data.method,
                    data.cache,
                    data.project_id,
                    data.project_name,
                )
            else:
                await create_Url(
                    data.id,
                    data.path,
                    sig,
                    data.method,
                    data.cache,
                    data.project_id,
                    data.project_name,
                )

            # Only mark safe routes for cache invalidation
            if cache_safe:
                changed_signatures.add(sig)

        # Invalidate only cache-safe routes
        for sig in changed_signatures:
            _ensure_version_exists(sig)
            _bump_route_version(sig)

        return JSONResponse(
            content={
                "detail": "URLs added successfully",
                "cache_disabled_for": skipped_cache
            },
            status_code=200
        )

    except Exception as e:
        return JSONResponse(
            content={"detail": f"Internal Server Error ---> {e}"},
            status_code=400
        )


@router.get("/getUrls/")
async def get_urls_endpoint(authorization: str = Header(None)):
    _auth_or_401(authorization)
    await check_url_table_exists()

    try:
        urls_data = await get_urls()
        return JSONResponse(content=urls_data, status_code=200)
    except Exception as e:
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.delete("/deleteUrl/")
async def delete_url_endpoint(data: DeleteUrlValidation = Body(), authorization: str = Header(None)):
    _auth_or_401(authorization)
    await check_url_table_exists()

    try:
        # Read before delete to get signature for invalidation
        existing = await get_url(data.id)
        sig = None
        if existing and isinstance(existing, dict):
            sig = _normalize_signature(existing.get("signature") or "")

        await delete_url(data.id)

        # Invalidate only that route
        if sig:
            _ensure_version_exists(sig)
            _bump_route_version(sig)

        return JSONResponse(content={"detail": f"Deleted URL with ID {data.id} successfully"}, status_code=200)

    except Exception as e:
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get("/clearCache/")
async def clear_cache(
        authorization: str = Header(None),
        signature: str | None = Query(default=None),
        url_id: int | None = Query(default=None),
        flush_all: bool = Query(default=True),
):
    """
    Clear cache safely.
    - If signature is provided: invalidate only that route.
    - If url_id is provided: lookup signature by id, invalidate only that route.
    - If none provided: reject (no more flush_all).
    """
    _auth_or_401(authorization)
    await check_url_table_exists()

    try:
        if flush_all:
            # English comment: Flush entire memcached instance
            cache.flush_all()
            return JSONResponse(
                content={"detail": "all cache flushed"},
                status_code=200,
            )
        sig = None

        if signature:
            sig = _normalize_signature(signature)

        if sig is None and url_id is not None:
            existing = await get_url(url_id)
            if existing and isinstance(existing, dict):
                sig = _normalize_signature(existing.get("signature") or "")

        if not sig:
            return JSONResponse(
                content={"detail": "signature or url_id is required. Global flush is disabled."},
                status_code=400,
            )

        _ensure_version_exists(sig)
        new_v = _bump_route_version(sig)

        return JSONResponse(
            content={"detail": "cache invalidated", "signature": sig, "new_version": new_v},
            status_code=200,
        )

    except Exception as e:
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get("/health/")
async def get_health():
    return {"status": 200}


@router.get("/getServersResource/")
async def get_servers_resource(request: Request):
    container_names = request.query_params.getlist("containerNames")
    resource_token = request.query_params.get("resourceToken")

    if not container_names or not resource_token:
        return JSONResponse(
            status_code=400,
            content={"code": 8901, "message": "containerNames and resourceToken are required"},
        )

    if resource_token != os.getenv("RESOURCE_TOKEN"):
        return JSONResponse(
            status_code=403,
            content={"code": 8937, "message": "Invalid resource token"},
        )

    try:
        client = docker.from_env()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"code": 8937, "message": "Docker connection failed", "error": str(e)},
        )

    # Server metrics
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    cpu_times = psutil.cpu_times_percent(interval=0.5)
    load_1, load_5, load_15 = os.getloadavg()
    net = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()

    server = {
        "cpu": {
            "usage_percent": psutil.cpu_percent(),
            "iowait_percent": cpu_times.iowait,
            "load_1m": load_1,
            "load_5m": load_5,
            "load_15m": load_15,
            "total_cores": psutil.cpu_count(logical=True),
        },
        "memory": {
            "used_mb": round(vm.used / 1024 / 1024, 2),
            "total_mb": round(vm.total / 1024 / 1024, 2),
            "available_mb": round(vm.available / 1024 / 1024, 2),
            "swap_used_mb": round(swap.used / 1024 / 1024, 2),
            "swap_total_mb": round(swap.total / 1024 / 1024, 2),
        },
        "disk": {
            "used_gb": round(disk.used / 1024 ** 3, 2),
            "total_gb": round(disk.total / 1024 ** 3, 2),
            "read_mb": round(disk_io.read_bytes / 1024 / 1024, 2),
            "write_mb": round(disk_io.write_bytes / 1024 / 1024, 2),
        },
        "network": {
            "rx_mb": round(net.bytes_recv / 1024 / 1024, 2),
            "tx_mb": round(net.bytes_sent / 1024 / 1024, 2),
            "rx_errors": net.errin,
            "tx_errors": net.errout,
        },
    }

    # Container metrics
    containers = []

    for name in container_names:
        try:
            container = client.containers.get(name)
            stats = container.stats(stream=False)
            attrs = container.attrs

            cpu_stats = stats["cpu_stats"]
            precpu = stats["precpu_stats"]

            cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
            system_delta = cpu_stats["system_cpu_usage"] - precpu["system_cpu_usage"]

            cpu_percent = 0.0
            if cpu_delta > 0 and system_delta > 0:
                cpu_count = len(cpu_stats["cpu_usage"].get("percpu_usage", []))
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100

            throttling = cpu_stats.get("throttling_data", {})

            mem_stats = stats["memory_stats"]
            mem_usage = mem_stats.get("usage", 0)
            mem_limit = mem_stats.get("limit", 0)
            mem_detail = mem_stats.get("stats", {})

            host_cfg = attrs.get("HostConfig", {})
            cpu_limit = None
            if host_cfg.get("NanoCpus", 0) > 0:
                cpu_limit = host_cfg["NanoCpus"] / 1e9
            elif host_cfg.get("CpuQuota", 0) > 0 and host_cfg.get("CpuPeriod", 0) > 0:
                cpu_limit = host_cfg["CpuQuota"] / host_cfg["CpuPeriod"]

            net_stats = stats.get("networks", {})
            rx_bytes = sum(n.get("rx_bytes", 0) for n in net_stats.values())
            tx_bytes = sum(n.get("tx_bytes", 0) for n in net_stats.values())
            rx_err = sum(n.get("rx_errors", 0) for n in net_stats.values())
            tx_err = sum(n.get("tx_errors", 0) for n in net_stats.values())

            containers.append(
                {
                    "name": name,
                    "status": attrs["State"]["Status"],
                    "started_at": attrs["State"]["StartedAt"],
                    "restart_count": attrs.get("RestartCount", 0),
                    "cpu": {
                        "usage_percent": round(cpu_percent, 2),
                        "limit_cores": cpu_limit,
                        "throttled_periods": throttling.get("throttled_periods"),
                        "throttled_time_ns": throttling.get("throttled_time"),
                    },
                    "memory": {
                        "used_mb": round(mem_usage / 1024 / 1024, 2),
                        "limit_mb": round(mem_limit / 1024 / 1024, 2),
                        "rss_mb": round(mem_detail.get("rss", 0) / 1024 / 1024, 2),
                        "cache_mb": round(mem_detail.get("cache", 0) / 1024 / 1024, 2),
                        "failcnt": mem_detail.get("failcnt"),
                        "oom_detected": mem_detail.get("oom_kill", 0) > 0,
                    },
                    "network": {
                        "rx_mb": round(rx_bytes / 1024 / 1024, 2),
                        "tx_mb": round(tx_bytes / 1024 / 1024, 2),
                        "rx_errors": rx_err,
                        "tx_errors": tx_err,
                    },
                    "disk": {
                        "writable_layer_mb": round(attrs.get("SizeRw", 0) / 1024 / 1024, 2)
                    },
                }
            )

        except docker.errors.NotFound:
            containers.append({"name": name, "error": "Container not found"})
        except Exception as e:
            containers.append({"name": name, "error": str(e)})

    client.close()

    return JSONResponse(
        status_code=200,
        content={
            "code": 8938,
            "timestamp": datetime.utcnow().isoformat(),
            "server": server,
            "containers": containers,
        },
    )
