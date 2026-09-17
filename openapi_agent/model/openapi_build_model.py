"""OpenAPI 构建相关模型：风险报告、diff 模型。"""

from typing import Any

from pydantic import BaseModel, Field


class RiskItem(BaseModel):
    """单条风险条目。确定性规则扫描与 LLM 扫描共用。"""

    path: str | None = None
    method: str | None = None
    scope: str | None = None
    issue: str | None = None
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        extra = data.pop("extra", {})
        data.update(extra)
        return data

    @classmethod
    def from_any(cls, raw: Any) -> "RiskItem":
        if isinstance(raw, dict):
            known = {k: v for k, v in raw.items() if k in cls.model_fields}
            unknown = {k: v for k, v in raw.items() if k not in cls.model_fields}
            item = cls(**known)
            item.extra = unknown
            return item
        return cls(issue=str(raw))


class RiskReport(BaseModel):
    """风险报告：冲突、缺失、AI 推测项。"""

    conflict_items: list[RiskItem] = Field(default_factory=list)
    ai_infer_items: list[RiskItem] = Field(default_factory=list)
    missing_info: list[RiskItem] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_items": [i.to_dict() for i in self.conflict_items],
            "ai_infer_items": [i.to_dict() for i in self.ai_infer_items],
            "missing_info": [i.to_dict() for i in self.missing_info],
        }


class DiffResult(BaseModel):
    """新旧 OpenAPI 对比结果。"""

    added: list[Any] = Field(default_factory=list)
    modified: dict[str, Any] = Field(default_factory=dict)
    deleted: list[Any] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
