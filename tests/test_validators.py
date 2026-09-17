"""入参校验与清洗工具（设计文档 2.4.2 / 2.7 / 2.8.1）。"""

import pytest

from openapi_agent.api.validators import (
    DEFAULT_INSTRUCTION,
    check_file_size,
    check_generate_mode,
    check_openapi_version,
    check_output_format,
    check_upload_count,
    parse_base_openapi,
    sanitize_instruction,
    unique_dest,
)
from openapi_agent.config import settings
from openapi_agent.core.errors import BusinessException, ErrorCode


def test_sanitize_instruction_blank_falls_back():
    assert sanitize_instruction("") == DEFAULT_INSTRUCTION
    assert sanitize_instruction(None) == DEFAULT_INSTRUCTION
    assert sanitize_instruction("   ") == DEFAULT_INSTRUCTION


def test_sanitize_instruction_strips_control_chars():
    assert sanitize_instruction("过滤\x00调试\x1f接口") == "过滤调试接口"


def test_sanitize_instruction_length_limit():
    ok = "a" * settings.user_instruction_max_len
    assert sanitize_instruction(ok) == ok
    with pytest.raises(BusinessException) as e:
        sanitize_instruction("a" * (settings.user_instruction_max_len + 1))
    assert int(e.value.code) == int(ErrorCode.INPUT_ERROR)
    assert "1000" in e.value.detail or str(settings.user_instruction_max_len) in e.value.detail


def test_parse_base_openapi_accepts_json_and_yaml():
    assert parse_base_openapi(None) is None
    assert parse_base_openapi("") is None
    yaml_doc = parse_base_openapi("openapi: 3.0.3\npaths:\n  /a:\n    get: {}\n")
    assert yaml_doc["paths"]["/a"]
    json_doc = parse_base_openapi('{"openapi": "3.0.3", "paths": {"/b": {}}}')
    assert "/b" in json_doc["paths"]
    assert parse_base_openapi({"paths": {"/c": {}}})["paths"] == {"/c": {}}


@pytest.mark.parametrize("bad", ["not: [valid", "[1,2,3]", '{"paths": []}'])
def test_parse_base_openapi_rejects_invalid(bad):
    with pytest.raises(BusinessException) as e:
        parse_base_openapi(bad)
    assert int(e.value.code) == int(ErrorCode.INPUT_ERROR)


def test_enum_checks():
    assert check_generate_mode("strict") == "strict"
    assert check_openapi_version("3.1.0") == "3.1.0"
    assert check_output_format("json") == "json"
    for fn, bad in (
        (check_generate_mode, "turbo"),
        (check_openapi_version, "2.0"),
        (check_output_format, "xml"),
    ):
        with pytest.raises(BusinessException) as e:
            fn(bad)
        assert int(e.value.code) == int(ErrorCode.INPUT_ERROR)


def test_upload_count_and_size_limits(monkeypatch):
    check_upload_count(settings.max_upload_files)
    with pytest.raises(BusinessException) as e:
        check_upload_count(settings.max_upload_files + 1)
    assert int(e.value.code) == int(ErrorCode.INPUT_ERROR)

    check_file_size("ok.md", 1024)
    with pytest.raises(BusinessException) as e:
        check_file_size("big.md", settings.max_file_size_bytes + 1)
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)


def test_unique_dest_avoids_overwrite():
    used: set[str] = set()
    first = unique_dest("/tmp/x", "same.md", used)
    second = unique_dest("/tmp/x", "same.md", used)
    third = unique_dest("/tmp/x", "same.md", used)
    assert first.endswith("same.md")
    assert second.endswith("same_1.md")
    assert third.endswith("same_2.md")

    # 多段扩展名只处理最后一段，且不同原文件名的首个候选不变
    assert unique_dest("/tmp/x", "a.tar.gz", used).endswith("a.tar.gz")
    assert unique_dest("/tmp/x", "a.tar.gz", used).endswith("a.tar_1.gz")
    assert unique_dest("/tmp/x", "other.md", used).endswith("other.md")
    # 空文件名兜底
    assert unique_dest("/tmp/x", "", used).endswith("upload.bin")


def test_unique_dest_strips_path_traversal():
    used: set[str] = set()
    assert unique_dest("/tmp/x", "../../etc/passwd", used).endswith("passwd")
