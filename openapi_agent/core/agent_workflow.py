import copy
import json
import logging
from typing import Callable

import yaml

from openapi_agent.config import settings as default_settings
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.task import TaskStatus
from openapi_agent.core.task_manager import TaskManager
from openapi_agent.model.intermediate_meta import ApiIntermediateMeta
from openapi_agent.builder.openapi_assembler import OpenApiAssembler
from openapi_agent.builder.diff_helper import DiffHelper
from openapi_agent.builder.validator import OpenApiValidator
from openapi_agent.material.extractor import MetaExtractor
from openapi_agent.material.preprocessor import MaterialPreprocessor
from openapi_agent.report.risk_report_builder import RiskReportBuilder

logger = logging.getLogger(__name__)

GENERATE_MODES = ("strict", "fast")

# 进度百分比（设计文档 2.2.2：Task.progress 为 0-100 的 int）
PROGRESS = {
    TaskStatus.PENDING: 0,
    TaskStatus.PREPROCESSING: 10,
    TaskStatus.CHUNKING: 20,
    TaskStatus.EXTRACTING: 40,
    TaskStatus.MERGING: 60,
    TaskStatus.ASSEMBLING: 75,
    TaskStatus.VALIDATING: 85,
    TaskStatus.DIFFING: 90,
    TaskStatus.COMPLETED: 100,
}

task_manager = TaskManager()


def set_status(task, status: TaskStatus) -> None:
    """推进任务状态并同步百分比进度（已取消的任务不被覆盖）。"""
    if task is not None and task.status != TaskStatus.CANCELLED:
        task.status = status
        task.progress = PROGRESS.get(status, task.progress)


class AgentWorkflow:
    """自研 Agent 主工作流（状态机编排全部业务步骤，设计文档 2.3.1）。"""

    def run(
        self,
        llm_client,
        preprocessor,
        extractor,
        base_spec: dict | None = None,
        title: str = "Generated API",
        version: str = "1.0.0",
        generate_mode: str = "strict",
        openapi_version: str = "3.0.3",
    ) -> tuple[list[ApiIntermediateMeta], dict]:
        chunks = preprocessor.process()
        metas = extractor.extract(llm_client, chunks=chunks)

        doc = OpenApiAssembler(
            metas,
            base_spec=base_spec,
            title=title,
            version=version,
            openapi_version=openapi_version,
        ).assemble()

        risk_report = RiskReportBuilder(metas, llm_client=llm_client).build()

        self._validate(doc, generate_mode, risk_report)

        diff = DiffHelper(base_spec, doc).diff() if base_spec else None

        result = {"openapi": doc, "diff": diff, "risk_report": risk_report}
        return metas, result

    def _validate(self, doc: dict, generate_mode: str, risk_report: dict) -> None:
        """strict：校验失败即抛错让任务失败；fast：不中断，写入风险报告。"""
        if generate_mode not in GENERATE_MODES:
            generate_mode = "strict"
        try:
            OpenApiValidator(doc).validate()
        except BusinessException as e:
            if generate_mode == "strict":
                raise
            risk_report.setdefault("validation_errors", []).append(
                {"code": int(e.code), "message": e.message, "detail": e.detail}
            )


async def run_task(
    task_id: str,
    paths: list[str],
    texts: list[str],
    user_instruction: str,
    output_format: str,
    title: str,
    version: str,
    *,
    base_spec: dict | None = None,
    generate_mode: str = "strict",
    openapi_version: str = "3.0.3",
    llm_client_factory: Callable[[], object] | None = None,
    settings_obj=None,
    cleanup: Callable[[], None] | None = None,
) -> None:
    """后台执行一次生成任务：预处理 → 抽取融合 → 组装 → 校验 → diff → 风险报告。"""
    import asyncio

    cfg = settings_obj or default_settings
    make_llm = llm_client_factory
    task = task_manager.get_task(task_id)
    try:
        set_status(task, TaskStatus.PREPROCESSING)
        preprocessor = MaterialPreprocessor(
            files=paths, texts=texts, settings=cfg, llm_getter=make_llm
        )
        set_status(task, TaskStatus.EXTRACTING)
        llm = make_llm()
        extractor = MetaExtractor(user_instruction=user_instruction)
        set_status(task, TaskStatus.MERGING)
        _, result = await asyncio.to_thread(
            AgentWorkflow().run,
            llm,
            preprocessor,
            extractor,
            base_spec,
            title,
            version,
            generate_mode,
            openapi_version,
        )
        set_status(task, TaskStatus.ASSEMBLING)
        doc = result["openapi"]
        spec_str = (
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
            if output_format == "yaml"
            else json.dumps(doc, ensure_ascii=False, indent=1)
        )
        if task is not None and task.status != TaskStatus.CANCELLED:
            risk_report = result["risk_report"]
            if preprocessor.warnings:
                risk_report["preprocess_warnings"] = list(preprocessor.warnings)
            task.result = {
                "openapi": spec_str,
                "diff": result["diff"],
                "risk_report": risk_report,
            }
            set_status(task, TaskStatus.COMPLETED)
    except asyncio.CancelledError:
        logger.info("任务已取消: %s", task_id)
    except BusinessException as e:
        if task is not None and task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.FAILED
            task.error_info = {"code": int(e.code), "message": e.message, "detail": e.detail}
    except Exception as e:
        logger.exception("任务内部错误: %s", task_id)
        if task is not None and task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.FAILED
            task.error_info = {"code": 10005, "message": "服务未知内部错误", "detail": str(e)}
    finally:
        # 素材只临时落盘：无论成功失败，都在这里回收（由调用方提供清理器）
        if cleanup is not None:
            cleanup()


async def run_with_timeout(coro, timeout_seconds: int | None = None, settings_obj=None) -> None:
    """给后台任务套一层超时（设计文档 2.8.1 ASYNC_WORKER_TIMEOUT）。"""
    import asyncio

    cfg = settings_obj or default_settings
    limit = cfg.async_worker_timeout if timeout_seconds is None else timeout_seconds
    if not limit or limit <= 0:
        await coro
        return
    try:
        await asyncio.wait_for(coro, timeout=limit)
    except asyncio.TimeoutError:
        raise BusinessException(
            ErrorCode.INTERNAL_ERROR,
            "任务执行超时",
            f"超出 ASYNC_WORKER_TIMEOUT={limit}s",
        )


__all__ = [
    "AgentWorkflow",
    "GENERATE_MODES",
    "PROGRESS",
    "task_manager",
    "set_status",
    "run_task",
    "run_with_timeout",
    "copy",
]
