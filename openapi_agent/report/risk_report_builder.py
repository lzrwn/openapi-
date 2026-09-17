import json
import logging

from pydantic import BaseModel, Field

from openapi_agent.core.errors import BusinessException
from openapi_agent.core.prompt_templates import BASE_SYSTEM, RISK_SCAN, render
from openapi_agent.model.intermediate_meta import ApiIntermediateMeta
from openapi_agent.model.openapi_build_model import RiskItem, RiskReport

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
        report = RiskReport(
            conflict_items=self._flagged("is_conflict"),
            ai_infer_items=self._flagged("is_ai_infer"),
            missing_info=self._missing(),
        )
        if self._llm is not None:
            self._merge_scan(report)
        return report.to_dict()

    def _flagged(self, attr: str) -> list[RiskItem]:
        return [
            RiskItem(path=m.path, method=m.method, notes=m.notes)
            for m in self._metas
            if getattr(m, attr)
        ]

    def _missing(self) -> list[RiskItem]:
        """确定性信息缺失扫描。

        只在「素材里确实没有」时才报缺失：例如已从返回示例推导出响应结构，
        就不再重复提示缺少响应（设计文档 2.4.1 功能4）。
        """
        issues: list[RiskItem] = []
        for m in self._metas:
            if m.method in BODY_METHODS and not m.request_body:
                issues.append(RiskItem(path=m.path, method=m.method, issue="缺少请求体定义"))
            if m.method == "GET" and not m.parameters:
                issues.append(RiskItem(path=m.path, method=m.method, issue="缺少查询参数说明"))
            if not m.response_examples:
                issues.append(RiskItem(path=m.path, method=m.method, issue="缺少响应结构定义"))
            if not m.summary or m.summary.strip() == f"{m.method} {m.path}":
                issues.append(
                    RiskItem(path=m.path, method=m.method, issue="缺少接口功能名称（summary）")
                )
        if self._metas and not any(m.response_examples for m in self._metas):
            issues.append(RiskItem(scope="global", issue="所有接口均未提取到响应结构与错误码定义"))
        if self._metas and not any((m.tag or "").strip() for m in self._metas):
            issues.append(RiskItem(scope="global", issue="未识别出业务分组（tag），已回落为路径首段"))
        return issues

    def _merge_scan(self, report: RiskReport) -> None:
        try:
            final_meta_list = json.dumps(
                [m.model_dump() for m in self._metas], ensure_ascii=False, indent=1
            )
            user = render(RISK_SCAN, final_meta_list=final_meta_list)
            scan: RiskScanResult = self._llm.chat_json(BASE_SYSTEM, user, RiskScanResult)
        except BusinessException as e:
            logger.warning("风险 LLM 扫描失败，仅保留确定性结果: %s", e)
            return
        report.missing_info += [RiskItem.from_any(i) for i in scan.missing_info]
        report.conflict_items += [RiskItem.from_any(i) for i in scan.conflict_items]
        report.ai_infer_items += [RiskItem.from_any(i) for i in scan.ai_infer_items]
