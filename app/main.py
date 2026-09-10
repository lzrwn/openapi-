import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.errors import BusinessException

ERROR_HTTP_STATUS = {
    10001: 400,
    10002: 404,
    10003: 422,
    10004: 503,
    10005: 500,
}


def _use_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


_use_utf8_stdio()

app = FastAPI(title="OpenAPI Generate Agent", version="0.1.0")
app.include_router(router)

_original_openapi = app.openapi


def _patched_openapi():
    if app.openapi_schema is None:
        schema = _original_openapi()
        for path_item in schema.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                media = (operation.get("requestBody") or {}).get("content", {}).get("multipart/form-data")
                if not media:
                    continue
                ref = media.get("schema", {}).get("$ref")
                if not ref:
                    continue
                props = schema["components"]["schemas"][ref.split("/")[-1]].get("properties", {})
                files = props.get("files")
                if files and files.get("type") == "array":
                    items = files.setdefault("items", {})
                    items["format"] = "binary"
                    items["contentEncoding"] = "binary"
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _patched_openapi


@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=ERROR_HTTP_STATUS.get(int(exc.code), 500),
        content={"code": int(exc.code), "message": exc.message, "detail": exc.detail},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
