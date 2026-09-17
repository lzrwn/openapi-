"""入参校验与清洗工具（设计文档 2.4.2 / 2.7 / 2.8.1）。"""

import json
import re

import yaml

from openapi_agent.config import GENERATE_MODES, OPENAPI_VERSIONS, OUTPUT_FORMATS, settings
from openapi_agent.core.errors import BusinessException, ErrorCode

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

DEFAULT_INSTRUCTION = "无特殊指令"


def sanitize_instruction(raw: str | None) -> str:
    """用户指令：去控制字符 → 长度校验 → 空值兜底（设计文档 2.4.2）。"""
    text = _CONTROL_CHARS.sub("", raw or "").strip()
    if not text:
        return DEFAULT_INSTRUCTION
    limit = settings.user_instruction_max_len
    if limit > 0 and len(text) > limit:
        raise BusinessException(
            ErrorCode.INPUT_ERROR,
            "参数非法，user_instruction过长",
            f"用户指令不能超过{limit}字符",
        )
    return text


def parse_base_openapi(raw: str | dict | None) -> dict | None:
    """解析基准 OpenAPI：支持 JSON / YAML 字符串或已解析的 dict。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        doc = raw
    else:
        text = (raw or "").strip()
        if not text:
            return None
        doc = None
        try:
            doc = json.loads(text)
        except Exception:
            try:
                doc = yaml.safe_load(text)
            except Exception as e:
                raise BusinessException(
                    ErrorCode.INPUT_ERROR, "参数非法，base_openapi 解析失败", str(e)
                )
        if not isinstance(doc, dict):
            raise BusinessException(
                ErrorCode.INPUT_ERROR, "参数非法，base_openapi 必须是 OpenAPI 文档对象", ""
            )
    paths = doc.get("paths")
    if paths is not None and not isinstance(paths, dict):
        raise BusinessException(
            ErrorCode.INPUT_ERROR, "参数非法，base_openapi.paths 必须是对象", ""
        )
    return doc


def check_generate_mode(mode: str) -> str:
    if mode not in GENERATE_MODES:
        raise BusinessException(
            ErrorCode.INPUT_ERROR, "输入参数错误", f"generate_mode 仅支持 {'/'.join(GENERATE_MODES)}"
        )
    return mode


def check_openapi_version(version: str) -> str:
    if version not in OPENAPI_VERSIONS:
        raise BusinessException(
            ErrorCode.INPUT_ERROR,
            "输入参数错误",
            f"openapi_version 仅支持 {'/'.join(OPENAPI_VERSIONS)}",
        )
    return version


def check_output_format(fmt: str) -> str:
    if fmt not in OUTPUT_FORMATS:
        raise BusinessException(
            ErrorCode.INPUT_ERROR, "输入参数错误", f"output_format 仅支持 {'/'.join(OUTPUT_FORMATS)}"
        )
    return fmt


def check_upload_count(count: int) -> None:
    limit = settings.max_upload_files
    if limit > 0 and count > limit:
        raise BusinessException(
            ErrorCode.INPUT_ERROR, "输入参数错误", f"最多上传 {limit} 个文件，当前 {count} 个"
        )


def check_file_size(name: str, size: int) -> None:
    limit = settings.max_file_size_bytes
    if limit > 0 and size > limit:
        raise BusinessException(
            ErrorCode.MATERIAL_ERROR,
            "素材解析错误或大小异常",
            f"{name} 大小 {size} 字节，超出单文件上限 {settings.max_file_size_mb}MB",
        )


def unique_dest(temp_dir, filename: str, used: set[str], prefix: str | None = None) -> str:
    """同名文件加序号后缀，避免相互覆盖（设计文档 2.3.1 临时素材管理）。

    prefix 用于「无法创建独立任务目录」时，把临时文件放进共享目录而不互相踩踏。
    """
    from pathlib import Path

    clean = Path(filename or "upload.bin").name
    base = f"{prefix}{clean}" if prefix else clean
    if base not in used:
        used.add(base)
        return str(Path(temp_dir) / base)
    stem, dot, suffix = base.rpartition(".")
    index = 1
    while True:
        candidate = f"{stem}_{index}{dot}{suffix}" if dot else f"{base}_{index}"
        if candidate not in used:
            used.add(candidate)
            return str(Path(temp_dir) / candidate)
        index += 1
