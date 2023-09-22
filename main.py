from fastapi import Request,Header
from fastapi import FastAPI
# from db.database import SessionLocal
# add models files here
# import middlewares
from starlette.middleware.base import BaseHTTPMiddleware
from gateWay import GateWay
# from middlewares.LogMiddleware import LogMiddleware
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# import routes


# add routes
# add middlewares

app.add_middleware(BaseHTTPMiddleware, dispatch=GateWay(Request,Header,'file.json'))
# app.add_middleware(BaseHTTPMiddleware, dispatch=GateWay())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# app.include_router(gateWay_routes)
