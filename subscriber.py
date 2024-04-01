# asyncio==3.4.3
# aio-pika==9.4.1
# pymongo==4.6.3

import asyncio
import aio_pika
import pymongo

RABBITMQ_HOST = '77.238.108.86'
RABBITMQ_PORT = 5672
RABBITMQ_USERNAME = 'gateway'
RABBITMQ_PASSWORD = 'Bgateway@1256'
RABBITMQ_VHOST = 'gateway'

async def consume_message_from_rabbitmq():
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
            queue = await channel.declare_queue()

            # Bind the queue to the exchange
            await queue.bind(exchange)

            async for message in queue:
                async with message.process():
                    try:
                        data={'body':message.body.decode()}
                        client = pymongo.MongoClient("mongodb://77.238.108.86:27000/log?retryWrites=true&w=majority")
                        db = client["logs"]
                        collection = db[message.routing_key]
                        result = collection.insert_one(data)
                        client.close()
                    except Exception as ex:
                        print(f"mongodb insertion faild with error : {ex}")

    except Exception as e:
        print(e)

# Run the subscriber coroutine
async def run_subscriber():
    await consume_message_from_rabbitmq()

async def main():
    await run_subscriber()

if __name__ == "__main__":
    asyncio.run(main())