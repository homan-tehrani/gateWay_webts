from fastapi import APIRouter, Body
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from API.urlSchema import AddUrlValidation, AddListUrlValidation, DeleteUrlValidation
from utils.db import get_url, get_urls, delete_url, update_Url, create_Url
from gateWay import cache

router = APIRouter(prefix='/url')


@router.post('/addUrl/')
async def add_url(datas: AddListUrlValidation = Body()):
    try:
        for data in datas.data:
            # validations
            try:
                data = AddUrlValidation(**data)
            except ValidationError as e:
                return JSONResponse(content={"detail": str(e)}, status_code=400)

            # check if URL already exists
            url = await get_url(data.signature)

            if url:
                # update
                await update_Url(data.path, data.signature, data.method, data.cache, url['id'])
            else:
                # create
                await create_Url(data.path, data.signature, data.method, data.cache)

        return JSONResponse(content={"detail": "URLs added successfully"}, status_code=200)

    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get('/getUrls/')
async def get_urls_endpoint():
    try:
        # Assuming conn and cursor are available in the current scope
        urls_data = await get_urls()
        return JSONResponse(content=urls_data, status_code=200)
    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.delete('/deleteUrl/')
async def delete_url_endpoint(data: DeleteUrlValidation = Body()):
    try:
        # Assuming conn and cursor are available in the current scope
        await delete_url(data.id)
        return JSONResponse(content={"detail": f"Deleted URL with ID {data.id} successfully"}, status_code=200)
    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get('/clearCache/')
async def clear_cache():
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
    return ({"status":200})