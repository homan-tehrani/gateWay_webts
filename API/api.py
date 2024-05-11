from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from API.urlSchema import AddUrlValidation, AddListUrlValidation, DeleteUrlValidation
from utils.db import get_url, get_urls, delete_url, update_Url, create_Url
from gateWay import cache
from dotenv import load_dotenv
import os

router = APIRouter(prefix='/url')
load_dotenv()

@router.post('/addUrl/')
async def add_url(datas: AddListUrlValidation = Body(),authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

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
                await update_Url(data.id, data.path, data.signature, data.method, data.cache)
            else:
                # create
                await create_Url(data.id, data.path, data.signature, data.method, data.cache)

        return JSONResponse(content={"detail": "URLs added successfully"}, status_code=200)

    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.get('/getUrls/')
async def get_urls_endpoint(authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

    try:
        # Assuming conn and cursor are available in the current scope
        urls_data = await get_urls()
        return JSONResponse(content=urls_data, status_code=200)
    except Exception as e:
        # Handle exceptions appropriately, for example, log the error
        return JSONResponse(content={"detail": f"Internal Server Error ---> {e}"}, status_code=400)


@router.delete('/deleteUrl/')
async def delete_url_endpoint(data: DeleteUrlValidation = Body(),authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

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
async def get_health(authorization: str = Header(None)):
    correct_token = str(os.getenv("TOKEN"))
    if authorization is None or authorization != correct_token:
        raise HTTPException(status_code=401, detail="کاربر احراز هویت نشده است")

    return ({"status":200})