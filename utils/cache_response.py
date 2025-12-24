from fastapi.responses import JSONResponse

def pack_response(resp: JSONResponse) -> dict:
    # JSONResponse does not expose .content
    # body is already JSON-serializable
    return {
        "status": resp.status_code,
        "body": resp.body.decode("utf-8")
    }

def unpack_response(data: dict) -> JSONResponse:
    return JSONResponse(
        content=json.loads(data["body"]),
        status_code=data["status"]
    )
