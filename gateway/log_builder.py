"""
Log payload construction + status matching.

The hot-path contract: ``should_log(status)`` is a single frozenset
membership test. Payload building (dict allocation, decoding,
truncation) happens ONLY after the status matched.
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from utils.global_variables import (
    LOG_BODY_MAX_BYTES,
    LOG_STATUS_CODES,
    SENSITIVE_HEADERS,
)

# ---------------------------------------------------------------------- #
# matcher
# ---------------------------------------------------------------------- #

def should_log(status_code: int) -> bool:
    """O(1) frozenset lookup -- the ONLY logging cost for normal traffic."""
    return status_code in LOG_STATUS_CODES


def is_error_status(status_code: int) -> bool:
    return status_code >= 500


# ---------------------------------------------------------------------- #
# payload
# ---------------------------------------------------------------------- #

def _redact_headers(headers: dict) -> dict:
    return {
        k: ("***" if k.lower() in SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def _truncate_body(body: bytes | None) -> tuple[str, bool]:
    if not body:
        return "", False
    truncated = len(body) > LOG_BODY_MAX_BYTES
    return body[:LOG_BODY_MAX_BYTES].decode("utf-8", errors="replace"), truncated


def build_log_payload(
    *,
    context: dict,
    signature: str | None,
    route_info: dict | None,
    upstream_url: str | None,
    response_status: int,
    response_headers: dict | None,
    response_body: bytes | None,
    event_type: str,
    duration_ms: float | None,
    container_info: dict | None = None,
) -> dict:
    req_body, req_trunc = _truncate_body(context.get("body"))
    resp_body, resp_trunc = _truncate_body(response_body)

    payload = {
        "schema_version": 1,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "request": {
            "method": context["method"],
            "url": context["full_url"],
            "path": context["path"],
            "query": context["query"],
            "headers": _redact_headers(context["headers"]),
            "body": req_body,
            "body_truncated": req_trunc,
            "client_ip": context.get("client_ip"),
        },
        "response": {
            "status_code": response_status,
            "headers": _redact_headers(response_headers or {}),
            "body": resp_body,
            "body_truncated": resp_trunc,
        },
        "route": {
            "signature": signature,
            "upstream_url": upstream_url,
            "project_id": (route_info or {}).get("project_id"),
            "project_name": (route_info or {}).get("project_name"),
        },
    }
    if container_info is not None:
        payload["container"] = container_info
    return payload


def upstream_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlsplit(url).hostname
    except Exception:
        return None
