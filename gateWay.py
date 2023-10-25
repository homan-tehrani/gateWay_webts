import http
import time
import memcache
import json
import requests
import threading
import os
from global_variables import LOG_URL
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi import APIRouter
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
router = APIRouter()
cache = memcache.Client([os.getenv('cacheIpAddress')])
# cache.flush_all()
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
            if not existUrl:
                thread = threading.Thread(target=saveLog, args=(request, 1200, self.body, 'not existUrl'))
                thread.start()
                return JSONResponse(content={"detail": "آدرس وجود ندارد"}, status_code=404)
            callService = await self.callService(request)
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
            try:
                signature = request.scope['path']
            except:
                signature = request.headers.get('referer')

            if 'authorization' in request.headers:
                self.token = request.headers['authorization']
            else:
                self.token = None
            self.method = request.method
            path = None
            try:
                path = cache.get(signature)
                if path is not None:
                    return path
            except:
                pass
            with open(self.fileUrl, "r") as json_file:
                Items = json.load(json_file)
                for item in Items:
                    if item['signature'] == signature:
                        if str(self.method).lower() != item['method']:
                            thread = threading.Thread(target=saveLog, args=(request, 1203, self.body, "self.method"))
                            thread.start()
                            return False
                        if 'path' not in item: return False
                        try:
                            cache.set(signature, item, time=int(os.getenv("cacheTime")))
                        except:
                            pass
                        path = item
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

    async def callService(self, request):
        try:
            contentType = request.headers.get("content-type")
            if self.method != "GET":
                headers = {'Content-Type': contentType, 'Authorization': self.token}
            else:
                headers = {'Authorization': self.token}
            if request.query_params:
                url = f"{self.path['path']}?{request.query_params}"
            else:
                url = f"{self.path['path']}"
            print("cache : ",self.path['cache'] , self.path['path'])
            print("cacheAddress",os.getenv('cacheIpAddress'))
            if self.path['cache'] == "False":
                print("url not in cache : ",self.path['cache'] , self.path['path'])
                response = requests.request(self.method, url, headers=headers, data=await request.body())
                return response
            try:
                response = cache.get(url)
                if response is None:
                    response = requests.request(self.method, url, headers=headers, data=await request.body())
                    print("URL 3",response.text)
                    if response.status_code==200:
                        cache.set(url, response, time=int(os.getenv("cacheTime")))
                return response
            except:
                response = requests.request(self.method, url, headers=headers, data=await request.body())
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
    url = os.getenv("LOG_URL")
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
