from fastapi import Request, Header
from fastapi import FastAPI

# import middleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from gateWay import GateWay

# import routes
from API.api import router as urls_router

app = FastAPI()
print("START 2")
app.add_middleware(BaseHTTPMiddleware, dispatch=GateWay(Request, Header))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

# import routes
from API.api import router as urls_router

print("START 3")
# including routers
app.include_router(urls_router, prefix='/v1')