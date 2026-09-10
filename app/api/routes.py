import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import yaml
from fastapi import APIRouter, File, Form, UploadFile

from app.agent.extractor import MetaExtractor
from app.agent.llm_client import LlmClient
from app.agent.workflow import AgentWorkflow
from app.core.errors import BusinessException, ErrorCode
from app.core.task import TaskStatus
from app.core.task_manager import TaskManager
from app.preprocessing.preprocessor import MaterialPreprocessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/openapi")

task_manager = TaskManager()
_running: dict[str, asyncio.Task] = {}


def _llm_client() -> LlmClient:
    base_url = os.environ.get("OPENAPI_AGENT_BASE_URL")
    api_key = os.environ.get("OPENAPI_AGENT_API_KEY")
    if not base_url or not api_key:
        raise BusinessException(
            ErrorCode.INTERNAL_ERROR,
            "缺少大模型服务配置",
            "请设置环境变量 OPENAPI_AGENT_BASE_URL / OPENAPI_AGENT_API_KEY",
        )
    return LlmClient(
        base_url=base_url,
        api_key=api_key,
        model=os.environ.get("OPENAPI_AGENT_MODEL", "gpt-4o-mini"),
    )


@router.post("/generate")
async def generate(
    files: list[UploadFile] = File(default=[]),
    texts: list[str] = Form(default=[]),
    user_instruction: str = Form(""),
    output_format: str = Form("yaml"),
    title: str = Form("Generated API"),
    version: str = Form("1.0.0"),
):
    if output_format not in ("yaml", "json"):
        raise BusinessException(ErrorCode.INPUT_ERROR, "输入参数错误", "output_format 仅支持 yaml/json")
    if not files and not texts:
        raise BusinessException(ErrorCode.INPUT_ERROR, "输入参数错误", "至少上传一个文件或提供一段文本素材")

    temp_dir = tempfile.mkdtemp(prefix="openapi-agent-")
    paths: list[str] = []
    try:
        for f in files:
            dest = Path(temp_dir) / Path(f.filename or "upload.bin").name
            content = await f.read()
            if not content:
                continue
            dest.write_bytes(content)
            paths.append(str(dest))
    except BusinessException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise BusinessException(ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", str(e))

    if not paths and not texts:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise BusinessException(ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", "上传文件均为空")

    materials = [{"type": "file", "name": Path(p).name} for p in paths]
    materials += [{"type": "text"} for _ in texts]
    task = task_manager.create_task(materials)

    async_task = asyncio.create_task(
        _run_task(
            task.task_id, paths, list(texts), user_instruction, output_format, title, version, temp_dir
        )
    )
    _running[task.task_id] = async_task
    return {"task_id": task.task_id}


async def _run_task(
    task_id: str,
    paths: list[str],
    texts: list[str],
    user_instruction: str,
    output_format: str,
    title: str,
    version: str,
    temp_dir: str,
):
    task = task_manager.get_task(task_id)
    try:
        task.status = TaskStatus.PREPROCESSING
        preprocessor = MaterialPreprocessor(files=paths, texts=texts)
        task.status = TaskStatus.EXTRACTING
        llm = _llm_client()
        extractor = MetaExtractor(user_instruction=user_instruction)
        _, result = await asyncio.to_thread(
            AgentWorkflow().run, llm, preprocessor, extractor, None, title, version
        )
        doc = result["openapi"]
        if output_format == "yaml":
            spec_str = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        else:
            spec_str = json.dumps(doc, ensure_ascii=False, indent=1)
        if task.status != TaskStatus.CANCELLED:
            task.result = {
                "openapi": spec_str,
                "diff": result["diff"],
                "risk_report": result["risk_report"],
            }
            task.status = TaskStatus.COMPLETED
    except asyncio.CancelledError:
        logger.info("任务已取消: %s", task_id)
    except BusinessException as e:
        if task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.FAILED
            task.error_info = {"code": int(e.code), "message": e.message, "detail": e.detail}
    except Exception as e:
        logger.exception("任务内部错误: %s", task_id)
        if task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.FAILED
            task.error_info = {"code": 10005, "message": "服务未知内部错误", "detail": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _running.pop(task_id, None)


def _require_task(task_id: str):
    task = task_manager.get_task(task_id)
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
            ErrorCode.TASK_NOT_FOUND, "任务执行失败，无可用结果", json.dumps(task.error_info, ensure_ascii=False)
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
    task_manager.cancel_task(task_id)
    running = _running.get(task_id)
    if running is not None:
        running.cancel()
    return {"task_id": task.task_id, "status": task.status.value}
