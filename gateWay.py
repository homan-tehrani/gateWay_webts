import http
import time
import memcache
import json
import requests
import threading
import os
from global_variables import LOG_URL
from fastapi import FastAPI, Request, Header, UploadFile, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi import APIRouter
from dotenv import load_dotenv
from db import get_url

load_dotenv()
app = FastAPI()
router = APIRouter()
cache = memcache.Client([os.getenv('CACHE_IP_ADDRESS')])


# cache.flush_all()
class GateWay:
    print('---------------------- in gateway',LOG_URL,cache)

    def __init__(self, request: Request, header):
        # init variables
        self.request = request
        self.headers = header
        self.token = None
        self.param = None
        self.method = None
        self.body = None
        self.path = None

    async def __call__(self, request: Request, call_next):
        print('----------------- in call')
        # try:

        # Check exist input URL
        existUrl = await self.existUrl(request)
        if not existUrl:
            # set loge for  does not exist url
            thread = threading.Thread(target=saveLog, args=(request, 1200, self.body, 'not existUrl'))
            thread.start()

            #  response for client
            return JSONResponse(content={"detail": "آدرس وجود ندارد"}, status_code=404)
        # file = await self.checkFile()
        # print(file)
        # print('[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[file]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]')

        # call reference api
        callService = await self.callService(request)

        try:
            callServiceContent = callService.json()
        except Exception as e:
            callServiceContent = callService.text
        if "id" in callServiceContent:

            thread = threading.Thread(target=saveLog, args=(request, callServiceContent['id'], self.body, callServiceContent))
            thread.start()
        # set loge for   success response api
        thread = threading.Thread(target=saveLog, args=(request, 1202, self.body, callServiceContent))
        thread.start()

        #  response for client
        return JSONResponse(content=callServiceContent, status_code=callService.status_code)
        # except Exception as e:
        #     thread = threading.Thread(target=saveLog, args=(request, 1198, self.body, f"{e}"))
        #     thread.start()
        #     return JSONResponse(content="__call__", status_code=400)

    async def parseUrl(self, request):
        # try:
        """
        Parses the URL from the incoming request and retrieves corresponding information.

        Args:
            request (FastAPI Request): The incoming request object.

        Returns:
            dict or bool: Returns the parsed URL information or False if not found.
        """
        # Extract headers from the request
        self.headers = request.headers

        # Try to get the signature from the request scope's path, fallback to referer header
        try:
            signature = request.scope['path']
        except Exception as e:
            print('Warning!', str(e))

            signature = request.headers.get('referer')

        # Check for authorization header and store the token
        if 'authorization' in request.headers:
            self.token = request.headers['authorization']
        else:
            self.token = None

        # Store the HTTP method
        self.method = request.method

        path = None
        try:
            # Try to get the path from the cache
            path = cache.get(signature)
            if path is not None:
                return path
        except Exception as e:
            print('Error!', str(e))

        # If path is not in cache, retrieve it from the database
        url = get_url(signature)

        if url:
            # Validate HTTP method
            if str(self.method).lower() != url['method']:
                # Log unauthorized method attempt
                thread = threading.Thread(target=saveLog, args=(request, 1203, self.body, "self.method"))
                thread.start()
                return False

            # Check if 'path' key is present in the retrieved URL
            if 'path' not in url or not url['path']:
                return False

            try:
                # Cache the URL with the specified cache time
                cache.set(signature, url, time=int(os.getenv("CACHE_TIME")))
            except Exception as e:
                print('Error!', str(e))

            path = url

        # Return the final path or False if not found
        if path:
            return path
        return False

    # except Exception as e:
    #     thread = threading.Thread(target=saveLog, args=(request, 1197, self.body, f"{e}"))
    #     thread.start()
    #     return JSONResponse(content="parseUrl", status_code=400)

    async def existUrl(self, request):
        # Attempt to parse the URL using the parseUrl method
        try:
            path = await self.parseUrl(request)

            # If a valid path is obtained, update self.path and return True
            if path:
                self.path = path
                return True

            # If no valid path is obtained, return False
            return False

        # Handle exceptions during the URL parsing
        except Exception as e:
            # Log the exception and create a new thread for asynchronous logging
            thread = threading.Thread(target=saveLog, args=(request, 1199, self.body, f"{e}"))
            thread.start()

            # Return a JSON response indicating an error with status code 400
            return JSONResponse(content="existUrl", status_code=400)

    async def callService(self, request):
        # try:
        # Extract the 'content-type' header from the request
        contentType = request.headers.get("content-type")

        # Check the HTTP method to determine the headers
        if self.method != "GET":
            headers = {'Content-Type': contentType, 'Authorization': self.token}
        else:
            headers = {'Authorization': self.token}

        # Construct the URL based on the request parameters
        if request.query_params:
            url = f"{self.path['path']}?{request.query_params}"
        else:
            url = f"{self.path['path']}"

        # Check if caching is disabled for this path
        if self.path['cache'] == "False":
            # Make a request to the external API without caching
            response = requests.request(self.method, url, headers=headers, data=await request.body())
            return response

        # Attempt to retrieve the response from the cache
        try:
            response = cache.get(url)

            # If the response is not in the cache, make a request to the external API
            if response is None:
                response = requests.request(self.method, url, headers=headers, data=await request.body())

                # If the request is successful, cache the response
                if response.status_code == 200:
                    cache.set(url, response, time=int(os.getenv("CACHE_TIME")))
            return response

        # Handle exceptions, print an error message, and make a request to the external API
        except Exception as e:
            print('Error!', str(e))
            response = requests.request(self.method, url, headers=headers, data=await request.body())
            return response
    # except Exception as e:
    #     thread = threading.Thread(target=saveLog, args=(request, 1196, self.body, f"{e}"))
    #     thread.start()
    #     return JSONResponse(content="callService", status_code=400)

    # async def checkFile(self, file: UploadFile = None):
    #     if file:
    #         return JSONResponse( content="File is required",status_code=400)
    #     return file


def saveLog(request, message_id, request_body, response_body=''):
    # Get the client's IP address using a custom function (get_client_ip)
    ip = get_client_ip(request)

    # Try to extract the user_id from the request's scope
    try:
        user_id = request.scope['User'].id
    except:
        # If user_id extraction fails, set it to 0
        user_id = 0

    # Retrieve the log URL from environment variables
    url = os.getenv("LOG_URL")

    # Convert request parameters and body to JSON format for logging
    request_body_json = json.dumps(
        {"param": request.scope['query_string'].decode(), "payload": request_body,
         "token": request.headers.get('authorization', '')})

    # Prepare the payload for logging
    payload = json.dumps(
        {"message_id": message_id, "user_id": user_id, "request_body": request_body_json,
         "response_body": f"{response_body}", "ip": ip, })

    # Set headers for the HTTP POST request to the log URL
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

    # Make an HTTP POST request to the log URL with the prepared payload
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
