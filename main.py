from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from utils.gateWay import GateWay

# import routes
from API.api import router as urls_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])


# including routers
app.include_router(urls_router, prefix='/v1')


@app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request):
    gateWay = GateWay(Request, Header)
    response = await gateWay.call(request)
    return response
