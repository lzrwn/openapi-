import json
import logging

from pydantic import BaseModel, Field

from app.agent.models import ApiIntermediateMeta
from app.agent.prompts import load_prompt, render
from app.core.errors import BusinessException

logger = logging.getLogger(__name__)

BODY_METHODS = {"POST", "PUT", "PATCH"}


class RiskScanResult(BaseModel):
    missing_info: list = Field(default_factory=list)
    conflict_items: list = Field(default_factory=list)
    ai_infer_items: list = Field(default_factory=list)


class RiskReportBuilder:
    def __init__(self, metas: list[ApiIntermediateMeta], llm_client=None):
        self._metas = metas
        self._llm = llm_client

    def build(self) -> dict:
        report = {
            "conflict_items": self._flagged("is_conflict"),
            "ai_infer_items": self._flagged("is_ai_infer"),
            "missing_info": self._missing(),
        }
        if self._llm is not None:
            self._merge_scan(report)
        return report

    def _flagged(self, attr: str) -> list[dict]:
        return [
            {"path": m.path, "method": m.method, "notes": m.notes}
            for m in self._metas
            if getattr(m, attr)
        ]

    def _missing(self) -> list[dict]:
        issues: list[dict] = []
        for m in self._metas:
            if m.method in BODY_METHODS and not m.request_body:
                issues.append({"path": m.path, "method": m.method, "issue": "缺少请求体定义"})
            if m.method == "GET" and not m.parameters:
                issues.append({"path": m.path, "method": m.method, "issue": "缺少查询参数说明"})
        if self._metas:
            issues.append(
                {"scope": "global", "issue": "所有接口均未提取到响应结构与错误码定义"}
            )
        return issues

    def _merge_scan(self, report: dict) -> None:
        try:
            final_meta_list = json.dumps(
                [m.model_dump() for m in self._metas], ensure_ascii=False, indent=1
            )
            system = load_prompt("base_system")
            user = render(load_prompt("risk_scan"), final_meta_list=final_meta_list)
            scan: RiskScanResult = self._llm.chat_json(system, user, RiskScanResult)
        except BusinessException as e:
            logger.warning("风险 LLM 扫描失败，仅保留确定性结果: %s", e)
            return
        report["missing_info"] += _as_items(scan.missing_info)
        report["conflict_items"] += _as_items(scan.conflict_items)
        report["ai_infer_items"] += _as_items(scan.ai_infer_items)


def _as_items(raw: list) -> list:
    return [item if isinstance(item, dict) else {"issue": str(item)} for item in raw]
