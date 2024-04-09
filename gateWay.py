import re
import httpx
import json
import memcache
import json
import requests
import asyncio
from utils.global_variables import LOG_URL, CACHE_TIME, CACHE_IP_ADDRESS
from fastapi import Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from utils.db import get_url
from utils.common import check_connection_cache,send_log_to_rabbitmq

cache = memcache.Client([CACHE_IP_ADDRESS])

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

    async def call(self, request: Request):        
        await check_connection_cache(cache, request)
        callService = None
        try:
            # Check exist input URL
            existUrl = await self.parseUrl(request)
            if not existUrl:
                asyncio.create_task(send_log_to_rabbitmq(request,1,f"address not found in parseUrl"))

                #  response for client
                return JSONResponse(content={"detail": "address not found"}, status_code=404)

            # call reference api
            callService = await self.callService(request)
            
            try:
                callServiceContent = callService.json()
            except Exception as e:
                callServiceContent = callService.text
            
            asyncio.create_task(send_log_to_rabbitmq(request,2,callService.text,callService.request.url,callService.status_code))
                
            #  response for client
            if str(callService.status_code)[0] != '2':
                return JSONResponse(content=f"service was error ", status_code=400)
            return JSONResponse(content=callServiceContent, status_code=callService.status_code)
        except Exception as e:
            asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in call function : {str(e)}"))
            return JSONResponse(content="error in call function", status_code=400)

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
                    self.path = path
                    # return path
            except Exception as e:
                asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in connect to cache server "))

                print('GateWayError! 1', str(e))

            # If path is not in cache, retrieve it from the database
            url = await get_url(signature)
            if url:

                # Validate HTTP method
                if str(self.method).lower() != url['method']:
                    asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in validate : {str(self.method).lower()} !== {url['method']}"))
                    return False

                # Check if 'path' key is present in the retrieved URL
                if 'path' not in url :
                    asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in validate : path not in  !== {json.dumps(url)}"))
                    return False

                try:
                    # Cache the URL
                    cache.set(signature, url, time=int(CACHE_TIME))
                except Exception as e:
                    asyncio.create_task(send_log_to_rabbitmq(request,1,f"caching url failed with error : {str(e)}"))
                path = url

            # Return the final path or False if not found
            if path:
                self.path = path
                return path
            asyncio.create_task(send_log_to_rabbitmq(request,1,f"this path dose not exist"))
            return False

        except Exception as e:
            asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in parse url : {json.dumps(url)}"))
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
            asyncio.create_task(send_log_to_rabbitmq(request,1,f"does not existUrl : {str(e)}"))
            return JSONResponse(content=f"does not existUrl ----> {e}", status_code=400)

    async def callService(self, request):
        try:
            # Extract the 'content-type' header from the request
            contentType = request.headers.get("content-type")

            headers = {}
            if self.token:
                headers['Authorization'] = self.token
            if contentType:
                headers['Content-Type'] = contentType

            # Construct the URL based on the request parameters
            if request.query_params:
                url = f"{self.path['path']}?{request.query_params}"
            else:
                url = f"{self.path['path']}"

            # Check if caching is disabled for this path
            if self.path['cache'] == 0:

                try:

                    # Make a request to the external API without caching
                    async with httpx.AsyncClient() as client:
                        if self.method.upper() == 'GET':
                            response = await client.get(url, headers=headers, timeout=30)
                        elif self.method.upper() == 'POST':
                            response = await client.post(url, headers=headers, data=await request.body(), timeout=30)
                        elif self.method.upper() == 'PUT':
                            response = await client.put(url, headers=headers, data=await request.body(), timeout=30)
                        elif self.method.upper() == 'DELETE':
                            response = await client.delete(url, headers=headers, data=await request.body(), timeout=30)
                        return response
                except:
                    response = requests.request(self.method, url, headers=headers, data=await request.body())
                    return response

            # Attempt to retrieve the response from the cache
            try:
                response = cache.get(url)
                # If the response is not in the cache, make a request to the external API
                if response is None:
                    try:
                        # Make a request to the external API without caching
                        async with httpx.AsyncClient() as client:
                            if self.method.upper() == 'GET':
                                response = await client.get(url, headers=headers, timeout=30)
                                print("DFSDF",response)
                            elif self.method.upper() == 'POST':
                                response = await client.post(url, headers=headers, data=await request.body(),
                                                             timeout=30)
                            elif self.method.upper() == 'PUT':
                                response = await client.put(url, headers=headers, data=await request.body(), timeout=30)
                            elif self.method.upper() == 'DELETE':
                                response = await client.delete(url, headers=headers, data=await request.body(),
                                                               timeout=30)
                    except:
                        response = requests.request(self.method, url, headers=headers, data=await request.body())
                        print('Get data with request' ,response.json())
                    # If the request is successful, cache the response
                    if response.status_code == 200:
                        cacheSet=cache.set(url, response, time=int(CACHE_TIME))
                        print(f'time  cache  : {CACHE_TIME}')
                        print(f' cache  status  set  is : {cacheSet}')

                return response

            # Handle exceptions, print an error message, and make a request to the external API
            except Exception as e:
                print('Error! cache.get ', str(e))
            try:

                # Make a request to the external API without caching
                async with httpx.AsyncClient() as client:
                    if self.method.upper() == 'GET':
                        response = await client.get(url, headers=headers, timeout=30)
                    elif self.method.upper() == 'POST':
                        response = await client.post(url, headers=headers, data=await request.body(), timeout=30)
                    elif self.method.upper() == 'PUT':
                        response = await client.put(url, headers=headers, data=await request.body(), timeout=30)
                    elif self.method.upper() == 'DELETE':
                        response = await client.delete(url, headers=headers, data=await request.body(), timeout=30)
                    return response
            except:
                response = requests.request(self.method, url, headers=headers, data=await request.body())
                return response
        except Exception as e:
            asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in call service : {str(e)}"))
            return JSONResponse(content=" error in callService", status_code=400)




def get_client_ip(request):
    try:
        if 'client' in request.scope:
            return request.scope['client'][0]
        return ""
    except Exception as e:
        asyncio.create_task(send_log_to_rabbitmq(request,1,f"error in get client ip : {str(e)}"))
        return JSONResponse(content="get_client_ip", status_code=400)
