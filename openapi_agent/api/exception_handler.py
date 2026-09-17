"""全局异常捕获，错误码统一封装（设计文档 2.2.1 / 2.1.2）。"""

from fastapi import Request
from fastapi.responses import JSONResponse

from openapi_agent.core.errors import BusinessException

ERROR_HTTP_STATUS = {
    10001: 400,
    10002: 404,
    10003: 422,
    10004: 503,
    10005: 500,
}


async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    """把 BusinessException 统一转为 {code, msg, detail} 错误 JSON。"""
    return JSONResponse(
        status_code=ERROR_HTTP_STATUS.get(int(exc.code), 500),
        content={"code": int(exc.code), "msg": exc.message, "detail": exc.detail},
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(BusinessException, business_exception_handler)
