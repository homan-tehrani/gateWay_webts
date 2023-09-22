from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fastapi import APIRouter
import json
import requests

app = FastAPI()
router = APIRouter()


class GateWay:
    def __init__(self, request: Request, header, fileUrl: str):
        self.request = request
        self.fileUrl = fileUrl
        self.headers = header
        self.token = None
        self.param = None
        self.method = None
        self.body = None
        self.path = None

    async def __call__(self, request: Request, call_next):
        existUrl = self.existUrl(request)
        self.body = await request.json()
        if not existUrl: return JSONResponse(content={"detail": "ادرس وجود ندارد"}, status_code=404)
        callService = self.callService(request)
        return JSONResponse(content=callService.json(), status_code=callService.status_code)

    def parseUrl(self, request):
        self.headers = request.headers
        if request.headers.get('referer'):
            signature = request.headers.get('referer')
        else:
            signature = request.scope['path']
        if 'authorization' in request.headers:
            self.token = request.headers['authorization']
        else:
            self.token = None
        self.method = request.method
        path = None
        with open(self.fileUrl, "r") as json_file:
            Items = json.load(json_file)
            for item in Items:
                if item['signature'] == signature:
                    if 'path' not in item: return False
                    path = item['path']
        if path:
            return path
        return False

    def existUrl(self, request):
        path = self.parseUrl(request)
        if path:
            self.path = path
            return True
        return False

    def callService(self, request):
        header = {'Authorization': self.token, 'Content-Type': 'application/json'}
        response = requests.request(self.method, f"{self.path}?{request.query_params}", headers=header, data=self.body)
        return response
