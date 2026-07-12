import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from gateway.gateway import Gateway, close_upstream_client
from gateway.log_publisher import log_publisher

# import routes
from API.api_new import router as urls_router

# Basic structured logging so logger.info/warning/exception are visible.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background RabbitMQ log worker once per worker process.
    await log_publisher.start()
    yield
    # Graceful shutdown: drain the log queue, close AMQP + upstream pool.
    await log_publisher.stop()
    await close_upstream_client()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # "*" origins + credentials is invalid; pick one
    allow_methods=["*"],
    allow_headers=["*"],
)

# including routers
app.include_router(urls_router, prefix="/v1")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(request: Request):
    gateway = Gateway(request)
    return await gateway.handle_request()
