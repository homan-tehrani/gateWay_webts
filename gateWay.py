import http
from global_variables import LOG_URL
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi import APIRouter
import json
import requests
import threading

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
        try:
            existUrl = self.existUrl(request)
            try:
                self.body = await request.json()
            except:
                self.body = await request.body()
                self.body = dict(self.body)
            if not existUrl:
                thread = threading.Thread(target=saveLog, args=(request, 1200, self.body, 'not existUrl'))
                thread.start()
                return JSONResponse(content={"detail": "ادرس وجود ندارد"}, status_code=404)
            callService = self.callService(request)
            try:
                callServiceContent = callService.json()
            except:
                callServiceContent = callService.text
            thread = threading.Thread(target=saveLog, args=(request, 1202, self.body, callServiceContent))
            thread.start()
            return JSONResponse(content=callServiceContent, status_code=callService.status_code)
        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 1198, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="__call__", status_code=400)

    def parseUrl(self, request):
        try:
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
        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 1197, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="parseUrl", status_code=400)

    def existUrl(self, request):
        try:
            path = self.parseUrl(request)
            if path:
                self.path = path
                return True
            return False
        except  Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 1199, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="existUrl", status_code=400)

    def callService(self, request):
        try:
            header = {'Authorization': self.token, 'Content-Type': 'application/json'}
            response = requests.request(self.method, f"{self.path}?{request.query_params}", headers=header,
                                        data=json.dumps(self.body))
            print(response)
            return response
        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 1196, self.body, f"{e}"))
            thread.start()

            return JSONResponse(content="callService", status_code=400)


def saveLog(request, message_id, request_body, response_body=''):
    ip = get_client_ip(request)
    try:
        user_id = request.scope['User'].id
    except:
        user_id = 0
    url = f"{LOG_URL}save-log"
    request_body_json = json.dumps(
        {"param": request.scope['query_string'].decode(), "payload": request_body,
         "token": request.headers.get('authorization', '')})
    payload = json.dumps(
        {"message_id": message_id, "user_id": user_id, "request_body": request_body_json,
         "response_body": f"{response_body}", "ip": ip, })
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    _response = requests.post(url, headers=headers, data=payload)


def get_client_ip(request):
    try:
        if 'client' in request.scope:
            return request.scope['client'][0]
        return ""
    except:
        thread = threading.Thread(target=saveLog, args=(request, 1195, request.body(), 'get_client_ip'))
        thread.start()
        return JSONResponse(content="get_client_ip", status_code=400)
