import hashlib
import time

def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()

def normalize_signature(path: str) -> str:
    return path if path.endswith("/") else path + "/"

def route_version_key(signature: str) -> str:
    return f"ver:route:{signature}"

def route_data_key(signature: str, version: int) -> str:
    return f"route:{signature}:v{version}"

def response_key(signature: str, version: int, method: str, query: str, body: bytes) -> str:
    return (
        f"resp:{signature}:v{version}:"
        f"{method}:"
        f"{sha1(query.encode())}:"
        f"{sha1(body or b'')}"
    )

def get_or_init_version(cache, key: str) -> int:
    v = cache.get(key)
    if v is None:
        cache.add(key, 1)
        return 1
    return int(v)

def bump_version(cache, key: str) -> int:
    v = cache.get(key)
    if v is None:
        cache.add(key, 1)
        return 1
    try:
        return cache.incr(key, 1)
    except Exception:
        new_v = int(time.time())
        cache.set(key, new_v)
        return new_v
