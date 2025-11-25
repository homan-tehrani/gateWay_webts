import os
from datetime import datetime

import docker
from API.urlSchema import AddUrlValidation, AddListUrlValidation, DeleteUrlValidation, GetServersResourceValidator
from dotenv import load_dotenv
from fastapi import APIRouter, Body, Header, HTTPException
from fastapi import Depends, APIRouter, Request
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
async def getServersResource(request: Request):
    # extract list of containers from querystring
    containerNames = request.query_params.getlist("containerNames")
    RESOURCE_TOKEN = str(os.getenv("RESOURCE_TOKEN"))

    # build params dict for validation
    params = dict(request.query_params)
    params["containerNames"] = containerNames

    # validate using pydantic
    try:
        query = GetServersResourceValidator(**params)
    except ValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"code": 8901, "message": "Validation failed", "errors": e.errors()}
        )

    # validate token
    if query.resourceToken != RESOURCE_TOKEN:
        return JSONResponse(
            status_code=403,
            content={"code": 8898, "message": "Invalid resource token"}
        )

    # try to init docker client
    try:
        client = docker.from_env()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"code": 8899, "message": "Docker connection failed", "error": str(e)}
        )

    results = []

    # iterate over containers
    for container_name in containerNames:
        try:
            container = client.containers.get(container_name)
            stats = container.stats(stream=False)

            # cpu calculation
            cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
            )

            cpu_percent = 0.0
            if cpu_delta > 0 and system_delta > 0:
                cpu_percent = (
                        cpu_delta / system_delta
                        * len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
                        * 100
                )

            # memory calculation
            mem_usage = stats["memory_stats"]["usage"] / (1024 * 1024)
            mem_limit = stats["memory_stats"]["limit"] / (1024 * 1024)
            mem_percent = (mem_usage / mem_limit * 100) if mem_limit else 0

            # network
            net_stats = stats.get("networks", {})
            rx_mb = sum(x["rx_bytes"] for x in net_stats.values()) / (1024 * 1024)
            tx_mb = sum(x["tx_bytes"] for x in net_stats.values()) / (1024 * 1024)

            # disk
            attrs = container.attrs
            disk_gb = round(attrs.get("SizeRw", 0) / (1024 ** 3), 2)

            results.append({
                "containerName": container_name,
                "timestamp": datetime.utcnow().isoformat(),
                "resources": {
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_percent": round(mem_percent, 2),
                    "memory_usage_mb": round(mem_usage, 2),
                    "disk_usage_gb": disk_gb,
                    "network_in_mb": round(rx_mb, 2),
                    "network_out_mb": round(tx_mb, 2),
                }
            })

        except docker.errors.NotFound:
            results.append({
                "containerName": container_name,
                "error": f"Container '{container_name}' not found"
            })

        except Exception as e:
            results.append({
                "containerName": container_name,
                "error": str(e)
            })

    # close docker client
    try:
        client.close()
    except:
        pass

    # final JSONResponse
    return JSONResponse(
        status_code=200,
        content={
            "code": 8899,
            "message": "Server resource fetched successfully",
            "data": results
        }
    )
