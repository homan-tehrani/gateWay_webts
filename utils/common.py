import httpx
import json
from datetime import datetime
import asyncio
import requests
import aio_pika
import json

from utils.global_variables import RABBITMQ_HOST,RABBITMQ_PASSWORD,RABBITMQ_PORT,RABBITMQ_USERNAME,RABBITMQ_VHOST


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
        except Exception:
            response = requests.request(method, url, headers=headers, data=data)
            return response

    except Exception as e:
        print("Error!", str(e))
        return False



async def check_connection_cache(cache, request):
    try:
        cache.set("testConnections", "connected to server  cache successfully", time=20)
        testConnections = cache.get("testConnections")
        if not testConnections:
            asyncio.create_task(send_log_to_rabbitmq(1,f"error in connect to cache server "))
    except Exception as e:
            asyncio.create_task(send_log_to_rabbitmq(1,f"error in connect to cache server : {str(e)}"))

async def send_log_to_rabbitmq(type,message,url=None):
    try:
        message=json.loads(message)
    except:
        pass
    data={'data':message}
    if url:
        data['url']=str(url)
    data=json.dumps(data,ensure_ascii=False).encode('utf8')
    try:
        connection = await aio_pika.connect_robust(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            login=RABBITMQ_USERNAME,
            password=RABBITMQ_PASSWORD,
            virtualhost=RABBITMQ_VHOST
        )

        async with connection:
            channel = await connection.channel()

            # Declare a fanout exchange
            exchange = await channel.declare_exchange('logs', aio_pika.ExchangeType.FANOUT)
            
            # Declare a queue
            if type==1:
                send_routing_key = 'gateway_logs'
            elif type==2:
                send_routing_key = 'requests_logs'

            # Publish a message to the exchange with a routing key
            await exchange.publish(
                aio_pika.Message(body=data),
                routing_key=send_routing_key
            )
            print("Message sent successfully")


    except Exception as e:
        print(e)


def check_and_convert_to_bytes(data):
    if isinstance(data, bytes):
        return data
    else:
        try:
            # Convert the variable to bytes
            return bytes(data, 'utf-8')
        except Exception as ex:
            print(f"Conversion to bytes failed with error: {ex}")
            return None