"""
Log payload construction + status matching.

Hot-path contract
-----------------
On the request path, the ONLY logging work allowed is:
  1. ``should_log(status)``        -> single frozenset membership test
  2. ``body_mode(content_type)``   -> single str.startswith check
  3. capped byte slices + one flat dict + one put_nowait

Everything expensive (multipart parsing, decoding, redaction, dict
building, JSON serialization) runs later, inside the publisher worker,
via ``build_log_payload``.

Binary bodies are never captured: uploads/downloads of files produce a
tiny placeholder string instead of megabytes of decoded garbage.
Multipart form-data is captured with a hard cap and file parts are
stripped in the worker, keeping only text form fields.
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from utils.global_variables import (
    LOG_BODY_MAX_BYTES,
    LOG_STATUS_CODES,
    SENSITIVE_HEADERS,
)

# Multipart bodies larger than this are assumed to contain files and are
# not captured at all (a placeholder is logged instead).
MULTIPART_SCAN_MAX_BYTES = 256 * 1024

# Max captured length for a single text form field inside multipart.
FORM_FIELD_MAX_CHARS = 512

# Content-type prefixes whose bodies are never captured.
_BINARY_CT_PREFIXES = (
    "image/",
    "video/",
    "audio/",
    "font/",
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/protobuf",
    "application/grpc",
)


# ---------------------------------------------------------------------- #
# hot-path helpers (request path) -- must stay allocation-light
# ---------------------------------------------------------------------- #

def should_log(status_code: int) -> bool:
    """O(1) frozenset lookup -- the ONLY logging cost for normal traffic."""
    return status_code in LOG_STATUS_CODES


def is_error_status(status_code: int) -> bool:
    return status_code >= 500


def body_mode(content_type: str | None) -> str:
    """
    Classify a body by content-type: 'skip' | 'multipart' | 'text'.
    One lowercase + one startswith -- effectively free.
    """
    if not content_type:
        return "text"
    ct = content_type.lower()
    if ct.startswith(_BINARY_CT_PREFIXES):
        return "skip"
    if ct.startswith("multipart/"):
        return "multipart"
    return "text"


def capture_body(body: bytes | None, content_type: str | None) -> tuple[bytes, bool, str | None]:
    """
    Decide, on the request path, what (if anything) to enqueue for a body.

    Returns (captured_bytes, truncated, note):
      - note is a short placeholder string when the body is intentionally
        not captured (binary, or oversized multipart). When note is set,
        captured_bytes is empty and the worker logs the note verbatim.
      - Otherwise captured_bytes is a capped slice for the worker to render.

    Cost: one startswith + at most one slice of bounded size.
    """
    if not body:
        return b"", False, None

    mode = body_mode(content_type)

    if mode == "skip":
        ct = (content_type or "").split(";")[0]
        return b"", True, f"<binary {ct}, {len(body)} bytes>"

    if mode == "multipart":
        # Oversized multipart almost certainly carries files: don't copy it.
        if len(body) > MULTIPART_SCAN_MAX_BYTES:
            return b"", True, f"<large multipart, {len(body)} bytes>"
        return bytes(body), False, None

    truncated = len(body) > LOG_BODY_MAX_BYTES
    return body[:LOG_BODY_MAX_BYTES], truncated, None


# ---------------------------------------------------------------------- #
# worker-side rendering (off the request path)
# ---------------------------------------------------------------------- #

def _strip_multipart_files(body: bytes, content_type: str) -> str:
    """
    Keep only text form fields from a multipart body; file parts are
    replaced with a '<file, N bytes>' placeholder. Boundary splitting
    only -- no full multipart parser needed for logging purposes.
    """
    idx = content_type.find("boundary=")
    if idx == -1:
        return "<multipart: no boundary>"
    boundary = content_type[idx + 9:].split(";")[0].strip().strip('"')
    delim = b"--" + boundary.encode()

    fields: list[str] = []
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, payload = part.partition(b"\r\n\r\n")
        head_lower = head.lower()

        # Extract the form field name from Content-Disposition.
        name = "?"
        n = head_lower.find(b'name="')
        if n != -1:
            end = head.find(b'"', n + 6)
            if end != -1:
                name = head[n + 6:end].decode("utf-8", "replace")

        # Any part carrying a filename (or an explicit binary type) is a file.
        if b"filename=" in head_lower or b"content-type: application/octet-stream" in head_lower:
            fields.append(f"{name}=<file, {len(payload)} bytes>")
        else:
            value = payload[:FORM_FIELD_MAX_CHARS].decode("utf-8", "replace").strip()
            fields.append(f"{name}={value}")

    return "; ".join(fields) or "<multipart: empty>"


def _render_body(captured: bytes, content_type: str | None, note: str | None) -> str:
    """Turn captured bytes into the string that goes into the log payload."""
    if note is not None:
        return note
    if not captured:
        return ""
    ct = (content_type or "").lower()
    if ct.startswith("multipart/"):
        return _strip_multipart_files(captured, ct)
    return captured.decode("utf-8", errors="replace")


def _redact_headers(headers: dict) -> dict:
    return {
        k: ("***" if k.lower() in SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def build_log_payload(item: dict) -> dict:
    """
    Build the final log payload from a raw enqueued item.
    Runs ONLY inside the publisher worker -- never on the request path.
    ``item`` is the flat dict produced by Gateway.maybe_log().
    """
    req_ct = item["req_headers"].get("content-type")
    resp_ct = (item["resp_headers"] or {}).get("content-type")

    payload = {
        "schema_version": 1,
        "event_type": item["event_type"],
        "timestamp": datetime.fromtimestamp(item["ts"], tz=timezone.utc).isoformat(),
        "duration_ms": item["duration_ms"],
        "request": {
            "method": item["method"],
            "url": item["full_url"],
            "path": item["path"],
            "query": item["query"],
            "headers": _redact_headers(item["req_headers"]),
            "body": _render_body(item["req_body"], req_ct, item["req_note"]),
            "body_truncated": item["req_trunc"],
            "client_ip": item["client_ip"],
        },
        "response": {
            "status_code": item["status"],
            "headers": _redact_headers(item["resp_headers"] or {}),
            "body": _render_body(item["resp_body"], resp_ct, item["resp_note"]),
            "body_truncated": item["resp_trunc"],
        },
        "route": {
            "signature": item["signature"],
            "upstream_url": item["upstream_url"],
            "project_id": (item["route_info"] or {}).get("project_id"),
            "project_name": (item["route_info"] or {}).get("project_name"),
        },
    }
    if item.get("container") is not None:
        payload["container"] = item["container"]
    return payload


def upstream_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlsplit(url).hostname
    except Exception:
        return None