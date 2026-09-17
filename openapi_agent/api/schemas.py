"""HTTP 请求/响应 Pydantic 模型（设计文档 2.2.1 api/schemas.py）。"""

from typing import Any

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """提交 OpenAPI 生成任务的入参（设计文档 2.1.1 输入参数示例）。"""

    files: list[str] = Field(default_factory=list, description="上传文件；multipart 下为文件流")
    text_materials: str = ""
    base_openapi: dict | None = None
    user_instruction: str = ""
    generate_mode: str = "strict"
    output_format: str = "yaml"
    openapi_version: str = "3.0.3"
    title: str = "Generated API"
    version: str = "1.0.0"


class TaskCreatedResponse(BaseModel):
    """任务提交响应。"""

    task_id: str
    status: str = "pending"
    msg: str = "任务已提交，开始解析素材"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int = 0
    error_info: dict[str, Any] | None = None


class TaskResultResponse(BaseModel):
    task_id: str
    status: str
    openapi: str
    diff: dict[str, Any] | None = None
    risk_report: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """统一错误响应体（设计文档 2.6.1）。"""

    code: int
    msg: str
    detail: str | None = None
