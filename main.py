from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, Header
from gateway.gateway import Gateway


# import routes
from API.api_new import router as urls_router

app = FastAPI()


# app.add_middleware(BaseHTTPMiddleware, dispatch=GateWay(Request, Header))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])


# including routers
app.include_router(urls_router, prefix='/v1')



@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request):
    gateway = Gateway(request)
    return await gateway.handle_request()
