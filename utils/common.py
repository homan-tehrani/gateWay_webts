import httpx
import json
from datetime import datetime


async def CallService(url, method, headers, data=None, time=30):
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

    except Exception as e:
        print("Error!", str(e))
        return False


async def CheckConnectionCache(cache):
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
