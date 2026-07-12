"""
Lightweight container status snapshot for error logs.

The Docker SDK is blocking and relatively expensive, so:
- It is called ONLY when a response status is in LOG_STATUS_CODES *and*
  the route maps to a known container.
- Results are cached per container for CONTAINER_INFO_TTL seconds, so an
  upstream outage producing thousands of 5xx per second triggers at most
  one Docker API call per TTL window.
- The blocking call runs in a small dedicated ThreadPoolExecutor and is
  awaited by the log worker, never by the request path.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from utils.global_variables import CONTAINER_INFO_TTL, CONTAINER_MAP

logger = logging.getLogger("gateway.container_inspector")

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docker-inspect")
_CACHE: dict[str, tuple[float, dict]] = {}
_docker_client = None  # lazy singleton


def resolve_container_name(project_name: str | None, upstream_host: str | None) -> str | None:
    """
    Map a route to a container name via the CONTAINER_MAP env var
    (JSON: {"project_name_or_host": "container_name"}).
    """
    if not CONTAINER_MAP:
        return None
    if project_name and project_name in CONTAINER_MAP:
        return CONTAINER_MAP[project_name]
    if upstream_host and upstream_host in CONTAINER_MAP:
        return CONTAINER_MAP[upstream_host]
    return None


def _inspect_blocking(name: str) -> dict:
    global _docker_client
    import docker  # local import: only paid for when actually needed

    if _docker_client is None:
        _docker_client = docker.from_env()

    try:
        container = _docker_client.containers.get(name)
        attrs = container.attrs
        state = attrs.get("State", {})
        return {
            "name": name,
            "status": state.get("Status"),
            "exit_code": state.get("ExitCode"),
            "oom_killed": state.get("OOMKilled"),
            "error": state.get("Error") or None,
            "restart_count": attrs.get("RestartCount", 0),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            # last few log lines are the most useful debugging signal
            "last_logs": container.logs(tail=20, timestamps=True)
            .decode(errors="replace"),
        }
    except docker.errors.NotFound:
        return {"name": name, "error": "container not found"}
    except Exception as exc:  # docker daemon unreachable etc.
        return {"name": name, "error": f"inspect failed: {exc}"}


async def get_container_info(name: str) -> dict:
    """Awaited by the log worker only. TTL-cached, executor-backed."""
    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached and now - cached[0] < CONTAINER_INFO_TTL:
        return cached[1]

    loop = asyncio.get_running_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(_EXECUTOR, _inspect_blocking, name),
            timeout=5,
        )
    except Exception:
        logger.exception("container inspect failed for %s", name)
        info = {"name": name, "error": "inspect timeout/failure"}

    _CACHE[name] = (now, info)
    return info
