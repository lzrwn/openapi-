import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.task import TaskStatus
from openapi_agent.core.task_manager import new_task_id
from openapi_agent.core import agent_workflow
from openapi_agent.api import service
from openapi_agent.api.validators import (
    check_file_size,
    check_generate_mode,
    check_openapi_version,
    check_output_format,
    check_upload_count,
    parse_base_openapi,
    sanitize_instruction,
    unique_dest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/openapi")


def _llm_client():
    """测试可替换的 LLM 客户端工厂。"""
    from openapi_agent.core.llm_factory import build_llm_client

    return build_llm_client()


def _materials_of(paths: list[str], texts: list[str]) -> list[dict]:
    materials = [{"type": "file", "name": Path(p).name} for p in paths]
    materials += [{"type": "text"} for _ in texts]
    return materials


@router.post("/generate")
async def generate(
    files: list[UploadFile] = File(default=[]),
    texts: list[str] = Form(default=[]),
    text_materials: list[str] = Form(default=[]),
    base_openapi: str = Form(""),
    user_instruction: str = Form(""),
    generate_mode: str = Form("strict"),
    output_format: str = Form("yaml"),
    openapi_version: str = Form("3.0.3"),
    title: str = Form("Generated API"),
    version: str = Form("1.0.0"),
):
    """提交 OpenAPI 生成任务（设计文档 2.1.1）。"""
    check_output_format(output_format)
    check_generate_mode(generate_mode)
    check_openapi_version(openapi_version)
    instruction = sanitize_instruction(user_instruction)
    base_spec = parse_base_openapi(base_openapi)

    texts = list(texts) + list(text_materials)
    if not files and not texts:
        raise BusinessException(ErrorCode.INPUT_ERROR, "输入参数错误", "至少上传一个文件或提供一段文本素材")
    check_upload_count(len(files))

    temp_materials = service.TempMaterials()
    paths: list[str] = []
    used: set[str] = set()
    try:
        for f in files:
            content = await f.read()
            if not content:
                continue
            check_file_size(Path(f.filename or "upload.bin").name, len(content))
            paths.append(temp_materials.write(f.filename or "upload.bin", content, used))
    except BusinessException:
        temp_materials.cleanup()
        raise
    except Exception as e:
        temp_materials.cleanup()
        raise BusinessException(ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", str(e))

    if not paths and not texts:
        temp_materials.cleanup()
        raise BusinessException(ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", "上传文件均为空")

    task_id = new_task_id()
    task = agent_workflow.task_manager.create_task(task_id, _materials_of(paths, texts))

    async def _job() -> None:
        try:
            await agent_workflow.run_with_timeout(
                agent_workflow.run_task(
                    task.task_id,
                    paths,
                    texts,
                    instruction,
                    output_format,
                    title,
                    version,
                    base_spec=base_spec,
                    generate_mode=generate_mode,
                    openapi_version=openapi_version,
                    llm_client_factory=_llm_client,
                    cleanup=temp_materials.cleanup,
                )
            )
        finally:
            temp_materials.cleanup()
            service.forget_running(task.task_id)

    async_task = asyncio.create_task(_job())
    service.register_running(task.task_id, async_task)
    return {"task_id": task.task_id, "status": "pending", "msg": "任务已提交，开始解析素材"}


def _require_task(task_id: str):
    task = agent_workflow.task_manager.get_task(task_id)
    if task is None:
        raise BusinessException(ErrorCode.TASK_NOT_FOUND, "task_id不存在", task_id)
    return task


@router.get("/task/{task_id}/status")
async def status(task_id: str):
    task = _require_task(task_id)
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "progress": task.progress,
        "error_info": task.error_info,
    }


@router.get("/task/{task_id}/result")
async def result(task_id: str):
    task = _require_task(task_id)
    if task.status == TaskStatus.FAILED:
        raise BusinessException(
            ErrorCode.TASK_NOT_FOUND,
            "任务执行失败，无可用结果",
            json.dumps(task.error_info, ensure_ascii=False),
        )
    if task.result is None:
        raise BusinessException(
            ErrorCode.INPUT_ERROR, "任务尚未完成", f"当前状态: {task.status.value}"
        )
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        **task.result,
    }


@router.post("/task/{task_id}/cancel")
async def cancel(task_id: str):
    task = _require_task(task_id)
    agent_workflow.task_manager.cancel_task(task_id)
    service.cancel_running(task_id)
    return {"task_id": task.task_id, "status": task.status.value}
