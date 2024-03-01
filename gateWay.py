import re
import memcache
import json
import requests
import threading
from utils.global_variables import LOG_URL, CACHE_TIME, CACHE_IP_ADDRESS
from fastapi import Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from utils.db import get_url

cache = memcache.Client([CACHE_IP_ADDRESS])

LOGIN_EXEMPT_URLS = ['/v/url/addUrl/', '/v/url/getUrls/', '/v/url/deleteUrl/', '/v/url/clearCache/', ]


# cache.flush_all()

class GateWay:
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
        order = r'[0 - 1 - 2 - 3 - 4 - 5 - 6 - 7 - 8 - 9]'
        path = request.scope['path']
        path = re.sub(order, '', path)
        if path in LOGIN_EXEMPT_URLS:
            response = await call_next(request)
            return response
        cache.set("testConnections", "connected to server  cache successfully", time=int(CACHE_TIME))
        testConnections = cache.get("testConnections")
        if not testConnections:
            # set loge for dont exist log code
            thread = threading.Thread(target=saveLog, args=(request, 4478, self.body, testConnections))
            thread.start()
            print('************* connected to server  cache fail :', testConnections, '********************')
        print(testConnections)

        try:

            # Check exist input URL
            existUrl = await self.existUrl(request)
            if not existUrl:
                # set loge for  does not exist url
                thread = threading.Thread(target=saveLog, args=(request, 4464, self.body, 'not existUrl'))
                thread.start()

                #  response for client
                return JSONResponse(content={"detail": "آدرس وجود ندارد"}, status_code=404)

            # call reference api
            print("apiCall",request)
            callService = await self.callService(request)
            print("apiCall response",callService)

            try:
                callServiceContent = callService.json()
            except Exception as e:
                callServiceContent = callService.text
            if callService.status_code == 500:
                thread = threading.Thread(target=saveLog, args=(request, 4465, self.body, f"{callServiceContent}"))
                thread.start()
                return JSONResponse(content=f"srvice was error {callServiceContent} ", status_code=400)

            if "id" in callServiceContent:
                thread = threading.Thread(target=saveLog,
                                          args=(request, callServiceContent['id'], self.body, callServiceContent))
                thread.start()
            else:
                # set loge for dont exist log code
                thread = threading.Thread(target=saveLog, args=(request, 4468, self.body, callServiceContent))
                thread.start()

            #  response for client
            return JSONResponse(content=callServiceContent, status_code=callService.status_code)
        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 4469, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="__call__", status_code=400)

    async def parseUrl(self, request):
        try:
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
            url = await get_url(signature)
            if url:

                # Validate HTTP method
                if str(self.method).lower() != url['method']:
                    # Log unauthorized method attempt
                    thread = threading.Thread(target=saveLog, args=(request, 4470, self.body, "self.method"))
                    thread.start()
                    return False

                # Check if 'path' key is present in the retrieved URL
                if 'path' not in url or not url['path']:
                    thread = threading.Thread(target=saveLog, args=(request, 4471, self.body, "self.method"))
                    thread.start()
                    return False

                try:
                    # Cache the URL with the specified cache time
                    cache.set(signature, url, time=int(CACHE_TIME))
                except Exception as e:
                    thread = threading.Thread(target=saveLog, args=(request, 4472, self.body, "cache.set"))
                    thread.start()
                    print('Error!', str(e))
                path = url

            # Return the final path or False if not found
            if path:
                return path
            thread = threading.Thread(target=saveLog, args=(request, 4473, self.body, "path dose not exist"))
            thread.start()
            return False

        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 4474, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="parseUrl", status_code=400)

    async def existUrl(self, request):

        # Attempt to parse the URL using the parseUrl method
        try:
            path = await self.parseUrl(request)
            # If a valid path is obtained, update self.path and return True
            if not path:
                return False
            self.path = path
            return True

        # Handle exceptions during the URL parsing
        except Exception as e:

            # Log the exception and create a new thread for asynchronous logging
            thread = threading.Thread(target=saveLog, args=(request, 4475, self.body, f"{e}"))
            thread.start()

            # Return a JSON response indicating an error with status code 400
            return JSONResponse(content=f"does not existUrl ----> {e}", status_code=400)

    async def callService(self, request):
        try:
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
            if self.path['cache'] == 0:
                # Make a request to the external API without caching
                print("--BUG NOT Cache URL ",url)
                response = requests.request(self.method, url, headers=headers, data=await request.body())
                print("-----BUG NOT Cache Reponse ", response.text)
                return response

            # Attempt to retrieve the response from the cache
            try:
                response = cache.get(url)
                # If the response is not in the cache, make a request to the external API
                if response is None:
                    print("BUG Get cache ", url)
                    response = requests.request(self.method, url, headers=headers, data=await request.body())
                    # If the request is successful, cache the response
                    if response.status_code == 200:
                        cache.set(url, response, time=int(CACHE_TIME))
                return response

            # Handle exceptions, print an error message, and make a request to the external API
            except Exception as e:
                print('Error!', str(e))
                response = requests.request(self.method, url, headers=headers, data=await request.body())
                return response
        except Exception as e:
            thread = threading.Thread(target=saveLog, args=(request, 4476, self.body, f"{e}"))
            thread.start()
            return JSONResponse(content="callService", status_code=400)


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

    # Convert request parameters and body to JSON format for logging
    request_body_json = json.dumps(
        {"param": request.scope['query_string'].decode(), "payload": request_body,
         "token": request.headers.get('authorization', ''), "header": str(request.scope)})

    # Prepare the payload for logging
    payload = json.dumps(
        {"message_id": message_id, "user_id": user_id, "request_body": request_body_json,
         "response_body": f"{response_body}", "ip": ip, })


    # Try to extract the user_id from the request's scope
    try:
        # Set headers for the HTTP POST request to the log URL
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        # Make an HTTP POST request to the log URL with the prepared payload
        _response = requests.post(LOG_URL, headers=headers, data=payload)
    except Exception as e:
        print("Log connection error",e)


def get_client_ip(request):
    try:
        if 'client' in request.scope:
            return request.scope['client'][0]
        return ""
    except:
        thread = threading.Thread(target=saveLog, args=(request, 4474, request.body(), 'get_client_ip'))
        thread.start()
        return JSONResponse(content="get_client_ip", status_code=400)
