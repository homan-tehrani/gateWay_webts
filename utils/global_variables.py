import json
import os

from dotenv import load_dotenv

load_dotenv()

# Site Url
AUTHENTICATION_SITE = os.getenv('AUTHENTICATION_SITE')
AUTHENTICATION_URL = f"{AUTHENTICATION_SITE}/user/auth/login_email/?site=project.sirafgroup.com"
GET_USER_URL = f"{AUTHENTICATION_SITE}/api/v1/user/userByToken/"

# URLs
CACHE_IP_ADDRESS = os.getenv('CACHE_IP_ADDRESS')
DB_NAME = os.getenv('DB_NAME')
CACHE_TIME = os.getenv('CACHE_TIME')
LOG_URL = os.getenv('LOG_URL')

GROUP_PROJECT_ID = os.getenv("GROUP_PROJECT_ID")
APIS_FOR_GATEWAY = os.getenv("APIS_FOR_GATEWAY")

# Rabbitmq
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST')
RABBITMQ_PORT = os.getenv('RABBITMQ_PORT')
RABBITMQ_USERNAME = os.getenv('RABBITMQ_USERNAME')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST')
RABBIT_EXCHANGE_NAME = os.getenv('RABBIT_EXCHANGE_NAME')


# --------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------- #

def _parse_status_codes(raw: str) -> frozenset[int]:
    """
    Parse "404,429,500-599" style config into a frozenset of ints.
    frozenset => O(1) membership check on the hot path.
    """
    codes: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            codes.update(range(int(lo), int(hi) + 1))
        else:
            codes.add(int(part))
    return frozenset(codes)


# Which response statuses trigger a log to RabbitMQ.
# Default: all server errors + 404 (unmatched routes) + 429.
LOG_STATUS_CODES = _parse_status_codes(
    os.getenv("LOG_STATUS_CODES", "404,429,500-599")
)

# Routing key used when publishing log messages.
LOG_ROUTING_KEY = os.getenv("LOG_ROUTING_KEY", "requests_logs")

# Bounded in-memory queue: if the broker is down/slow we drop logs
# instead of growing memory or slowing requests.
LOG_QUEUE_MAXSIZE = int(os.getenv("LOG_QUEUE_MAXSIZE", "10000"))

# Max bytes of request/response body included in a log message.
LOG_BODY_MAX_BYTES = int(os.getenv("LOG_BODY_MAX_BYTES", "4096"))

# Headers whose values are redacted in logs.
SENSITIVE_HEADERS = frozenset(
    h.strip().lower()
    for h in os.getenv(
        "LOG_SENSITIVE_HEADERS",
        "authorization,cookie,set-cookie,x-api-key,proxy-authorization",
    ).split(",")
    if h.strip()
)

# Optional JSON map {"project_name_or_upstream_host": "container_name"}
# used to attach container status to error logs.
try:
    CONTAINER_MAP: dict = json.loads(os.getenv("CONTAINER_MAP", "") or "{}")
except json.JSONDecodeError:
    CONTAINER_MAP = {}

# TTL (seconds) for the cached container inspection result.
CONTAINER_INFO_TTL = int(os.getenv("CONTAINER_INFO_TTL", "30"))

# Master switches
DO_LOG = int(os.getenv("DO_LOG", "1"))  # 0=off, 1=on
LOG_TO_RABBITMQ = int(os.getenv("LOG_TO_RABBITMQ", "1"))
LOG_TO_SENTRY = int(os.getenv("LOG_TO_SENTRY", "0"))
LOG_QUEUE_NAME = os.getenv("LOG_QUEUE_NAME", "gateway.logs")
RABBIT_AUTO_MIGRATE = int(os.getenv("RABBIT_AUTO_MIGRATE", "1"))

LOG_QUEUE_MAX_BYTES = 32 * 1024 * 1024  # سقف رم صف لاگ per worker
LOG_MAX_PER_SECOND = 100  # سقف نرخ enqueue
CACHE_MAX_BODY_BYTES = 512 * 1024  # پاسخ بزرگ‌تر cache نمی‌شه

ACCESS_LOG_ENABLED = int(os.getenv("ACCESS_LOG_ENABLED", "1"))
ACCESS_QUEUE_NAME = os.getenv("ACCESS_QUEUE_NAME", "gateway.access")
ACCESS_ROUTING_KEY = os.getenv("ACCESS_ROUTING_KEY", "access")
ACCESS_QUEUE_MAXSIZE = 10_000  # ~2MB RAM ceiling per worker
ACCESS_BATCH_MAX = 200  # records per published message
ACCESS_FLUSH_SECONDS = 1.0  # max delay before a partial batch ships
