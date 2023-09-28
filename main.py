from fastapi import Request,Header
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from gateWay import GateWay
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()



app.add_middleware(BaseHTTPMiddleware, dispatch=GateWay(Request,Header,'file.json'))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


