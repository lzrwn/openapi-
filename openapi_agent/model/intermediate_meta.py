from typing import Any

from pydantic import BaseModel, Field


class ApiIntermediateMeta(BaseModel):
    """【核心】接口中间元数据模型（不是 OpenAPI 文档结构）。"""

    path: str
    method: str
    summary: str = ""
    # 业务分组名（中文），由模型按业务语义给出；为空时组装器回落到路径首段
    tag: str = ""
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    request_body: dict[str, Any] | None = None
    response_examples: list | dict | None = None
    error_codes: list[Any] = Field(default_factory=list)
    source: str = ""
    is_conflict: bool = False
    is_ai_infer: bool = False
    notes: list[str] = Field(default_factory=list)
