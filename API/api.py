import os
from datetime import datetime

import docker
import psutil

from API.urlSchema import AddUrlValidation, AddListUrlValidation, DeleteUrlValidation, GetServersResourceValidator
from dotenv import load_dotenv
from fastapi import APIRouter, Body, Header, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from gateWay import cache
from pydantic import ValidationError
from utils.db import get_url, get_urls, delete_url, update_Url, create_Url, check_url_table_exists

router = APIRouter(prefix='/url')
load_dotenv()


@router.post('/addUrl/')
async def add_url(datas: AddListUrlValidation = Body(), authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")
    await check_url_table_exists()

    try:

        for data in datas.data:
            # validations
            try:
                data = AddUrlValidation(**data)
            except ValidationError as e:
                return JSONResponse(content={"detail": str(e)}, status_code=400)

            # check if URL already exists
            url = await get_url(data.id)

            if url:
                # update
                await update_Url(data.id, data.path, data.signature, data.method, data.cache, data.project_id,
                                 data.project_name)
            else:
                # create
                await create_Url(data.id, data.path, data.signature, data.method, data.cache, data.project_id,
                                 data.project_name)

        return JSONResponse(content={"detail": "URLs added successfully"}, status_code=200)

    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get('/getUrls/')
async def get_urls_endpoint(authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

    await check_url_table_exists()

    try:
        # Assuming conn and cursor are available in the current scope
        urls_data = await get_urls()
        return JSONResponse(content=urls_data, status_code=200)
    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.delete('/deleteUrl/')
async def delete_url_endpoint(data: DeleteUrlValidation = Body(), authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

    await check_url_table_exists()

    try:
        # Assuming conn and cursor are available in the current scope
        await delete_url(data.id)
        return JSONResponse(content={"detail": f"Deleted URL with ID {data.id} successfully"}, status_code=200)
    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get('/clearCache/')
async def clear_cache(authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

    await check_url_table_exists()

    try:
        # Flush all items from the cache
        cache.flush_all()
        # Optionally, close the connection
        cache.disconnect_all()
        return JSONResponse(content={"detail": f"clear cache successfully"}, status_code=200)

    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get("/health/")
async def get_health():
    return ({"status": 200})


@router.get("/getServersResource/")
async def get_servers_resource(request: Request):
    container_names = request.query_params.getlist("containerNames")
    resource_token = request.query_params.get("resourceToken")

    if not container_names or not resource_token:
        return JSONResponse(
            status_code=400,
            content={"code": 8901, "message": "containerNames and resourceToken are required"}
        )

    if resource_token != os.getenv("RESOURCE_TOKEN"):
        return JSONResponse(
            status_code=403,
            content={"code": 8937, "message": "Invalid resource token"}
        )

    try:
        client = docker.from_env()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"code": 8937, "message": "Docker connection failed", "error": str(e)}
        )

    # ================= SERVER METRICS =================

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
            "total_cores": psutil.cpu_count(logical=True)
        },
        "memory": {
            "used_mb": round(vm.used / 1024 / 1024, 2),
            "total_mb": round(vm.total / 1024 / 1024, 2),
            "available_mb": round(vm.available / 1024 / 1024, 2),
            "swap_used_mb": round(swap.used / 1024 / 1024, 2),
            "swap_total_mb": round(swap.total / 1024 / 1024, 2)
        },
        "disk": {
            "used_gb": round(disk.used / 1024 ** 3, 2),
            "total_gb": round(disk.total / 1024 ** 3, 2),
            "read_mb": round(disk_io.read_bytes / 1024 / 1024, 2),
            "write_mb": round(disk_io.write_bytes / 1024 / 1024, 2)
        },
        "network": {
            "rx_mb": round(net.bytes_recv / 1024 / 1024, 2),
            "tx_mb": round(net.bytes_sent / 1024 / 1024, 2),
            "rx_errors": net.errin,
            "tx_errors": net.errout
        }
    }

    # ================= CONTAINER METRICS =================

    containers = []

    for name in container_names:
        try:
            container = client.containers.get(name)
            stats = container.stats(stream=False)
            attrs = container.attrs

            cpu_stats = stats["cpu_stats"]
            precpu = stats["precpu_stats"]

            cpu_delta = (
                cpu_stats["cpu_usage"]["total_usage"]
                - precpu["cpu_usage"]["total_usage"]
            )
            system_delta = (
                cpu_stats["system_cpu_usage"]
                - precpu["system_cpu_usage"]
            )

            cpu_percent = 0.0
            if cpu_delta > 0 and system_delta > 0:
                cpu_count = len(cpu_stats["cpu_usage"].get("percpu_usage", []))
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100

            throttling = cpu_stats.get("throttling_data", {})

            mem_stats = stats["memory_stats"]
            mem_usage = mem_stats.get("usage", 0)
            mem_limit = mem_stats.get("limit", 0)
            mem_detail = mem_stats.get("stats", {})

            host_cfg = attrs["HostConfig"]
            cpu_limit = None
            if host_cfg.get("NanoCpus", 0) > 0:
                cpu_limit = host_cfg["NanoCpus"] / 1e9
            elif host_cfg.get("CpuQuota", 0) > 0:
                cpu_limit = host_cfg["CpuQuota"] / host_cfg["CpuPeriod"]

            net_stats = stats.get("networks", {})
            rx_bytes = sum(n["rx_bytes"] for n in net_stats.values())
            tx_bytes = sum(n["tx_bytes"] for n in net_stats.values())
            rx_err = sum(n.get("rx_errors", 0) for n in net_stats.values())
            tx_err = sum(n.get("tx_errors", 0) for n in net_stats.values())

            containers.append({
                "name": name,
                "status": attrs["State"]["Status"],
                "started_at": attrs["State"]["StartedAt"],
                "restart_count": attrs["RestartCount"],
                "cpu": {
                    "usage_percent": round(cpu_percent, 2),
                    "limit_cores": cpu_limit,
                    "throttled_periods": throttling.get("throttled_periods"),
                    "throttled_time_ns": throttling.get("throttled_time")
                },
                "memory": {
                    "used_mb": round(mem_usage / 1024 / 1024, 2),
                    "limit_mb": round(mem_limit / 1024 / 1024, 2),
                    "rss_mb": round(mem_detail.get("rss", 0) / 1024 / 1024, 2),
                    "cache_mb": round(mem_detail.get("cache", 0) / 1024 / 1024, 2),
                    "failcnt": mem_detail.get("failcnt"),
                    "oom_detected": mem_detail.get("oom_kill", 0) > 0
                },
                "network": {
                    "rx_mb": round(rx_bytes / 1024 / 1024, 2),
                    "tx_mb": round(tx_bytes / 1024 / 1024, 2),
                    "rx_errors": rx_err,
                    "tx_errors": tx_err
                },
                "disk": {
                    "writable_layer_mb": round(attrs.get("SizeRw", 0) / 1024 / 1024, 2)
                }
            })

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
            "containers": containers
        }
    )

