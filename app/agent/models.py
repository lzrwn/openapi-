from typing import Any

from pydantic import BaseModel, Field


class ApiIntermediateMeta(BaseModel):
    path: str
    method: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    request_body: dict[str, Any] | None = None
    source: str = ""
    is_conflict: bool = False
    is_ai_infer: bool = False
    notes: list[str] = Field(default_factory=list)
