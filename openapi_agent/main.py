import sys
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from openapi_agent.api.exception_handler import register_exception_handlers
from openapi_agent.api.routes import router
from openapi_agent.config import settings

app = FastAPI(title="OpenAPI Generate Agent", version="0.1.0")
app.include_router(router)
register_exception_handlers(app)


def _configure_temp_root() -> None:
    """上传素材的临时目录根路径。

    默认使用系统临时目录；容器/沙箱部署时用 OPENAPI_AGENT_TEMP_ROOT 指到可写卷，
    保证素材只临时落盘、任务结束后立即清理。
    """
    if not settings.temp_root:
        return
    root = Path(settings.temp_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:  # 不可写时退回系统临时目录
        return
    tempfile.tempdir = str(root)


def _use_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


_use_utf8_stdio()
_configure_temp_root()

_original_openapi = app.openapi


def _patched_openapi():
    """把 files 字段标注为 binary，便于 /docs 直接上传文件。"""
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
