import httpx
import json
from datetime import datetime
import threading
import requests


async def CallService(url, method, headers, data=None, time=30):
    try:
        try:

            async with httpx.AsyncClient() as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers, timeout=time)
                elif method.upper() == 'POST':
                    data = json.dumps(data)
                    response = await client.post(url, headers=headers, data=data, timeout=time)
                elif method.upper() == 'PUT':
                    response = await client.put(url, headers=headers, data=data, timeout=time)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=headers, data=data, timeout=time)
                return response
        except Exception as e :
            print("Error in httpx.AsyncClient()  !", str(e))

            response = requests.request(method, url, headers=headers, data=data)
            return response

    except Exception as e:
        print("Error!", str(e))
        return False


def saveLog(request, message_id, request_body, response_body=''):
    return True
    # Get the client's IP address using a custom function (get_client_ip)
    ip = '0'

    # Try to extract the user_id from the request's scope
    try:
        user_id = request.scope['User'].id
    except:
        # If user_id extraction fails, set it to 0
        user_id = 0

    # Retrieve the log URL from environment variables
    try:
        # Convert request parameters and body to JSON format for logging
        request_body_json = json.dumps(
            {"param": request.scope['query_string'].decode(), "payload": request_body,
             "token": request.headers.get('authorization', ''), "header": str(request.scope)})

        # Prepare the payload for logging
        payload = json.dumps(
            {"message_id": message_id, "user_id": user_id, "request_body": request_body_json,
             "response_body": f"{response_body}", "ip": ip, })

        # Try to extract the user_id from the request's scope
        # Set headers for the HTTP POST request to the log URL
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        # Make an HTTP POST request to the log URL with the prepared payload
        _response = requests.post(LOG_URL, headers=headers, data=payload)
    except Exception as e:
        print(" GateWayError Log connection error", str(e))


async def CheckConnectionCache(cache, request):
    #   test  connection cache server
    cache.set("testConnections", "connected to server  cache successfully", time=20)
    testConnections = cache.get("testConnections")
    if not testConnections:
        # set loge for dont exist log code
        thread = threading.Thread(target=saveLog, args=(request, 4478, 'self.body', testConnections))
        thread.start()
        print('********************* connected to server  cache fail :', testConnections, '********************')
    else:
        print('-------------------- connected to server  cache :', testConnections, '------------------')
