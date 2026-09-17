"""入参校验、生成模式、基准 OpenAPI 增量、任务状态上报。"""

import time

import pytest
import yaml
from fastapi.testclient import TestClient

import openapi_agent.api.routes as routes
from openapi_agent.config import settings
from openapi_agent.main import app
from tests.fakes import FakeLlmClient

BASE_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Base API", "version": "0.9.0"},
    "paths": {"/legacy": {"get": {"summary": "旧接口", "responses": {"200": {"description": "OK"}}}}},
}


def _wait_terminal(client: TestClient, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/openapi/task/{task_id}/status").json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内结束: {body}")


def _fake_llm(**kwargs) -> FakeLlmClient:
    return FakeLlmClient(
        defaults={
            "ExtractionResult": {
                "endpoints": [{"path": "/pets", "method": "GET", "source_type": "markdown"}]
            }
        },
        **kwargs,
    )


def _generate(client: TestClient, **data) -> dict:
    payload = {"text_materials": ["获取宠物列表接口 GET /pets，返回宠物集合。"]}
    payload.update(data)
    return client.post("/api/v1/openapi/generate", data=payload)


# ---------- 入参校验 ----------


@pytest.mark.parametrize(
    "field,value",
    [
        ("output_format", "xml"),
        ("generate_mode", "turbo"),
        ("openapi_version", "2.0"),
    ],
)
def test_invalid_enum_params_return_10001(monkeypatch, field, value):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        r = _generate(client, **{field: value})
    assert r.status_code == 400
    assert r.json()["code"] == 10001
    assert "msg" in r.json()


def test_too_long_user_instruction_returns_10001(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        r = _generate(client, user_instruction="x" * (settings.user_instruction_max_len + 1))
    assert r.status_code == 400
    assert r.json()["code"] == 10001
    assert str(settings.user_instruction_max_len) in (r.json()["detail"] or "")


def test_too_many_files_returns_10001(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    files = [
        ("files", (f"f{i}.md", b"GET /x interface description text", "text/markdown"))
        for i in range(settings.max_upload_files + 1)
    ]
    with TestClient(app) as client:
        r = client.post("/api/v1/openapi/generate", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == 10001


def test_oversized_file_returns_10003(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    monkeypatch.setattr(type(settings), "max_file_size_bytes", property(lambda self: 10))
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/openapi/generate",
            files=[("files", ("big.md", b"y" * 100, "text/markdown"))],
        )
    assert r.status_code == 422
    assert r.json()["code"] == 10003


def test_empty_input_returns_10001():
    with TestClient(app) as client:
        r = client.post("/api/v1/openapi/generate", data={"text_materials": []})
    assert r.status_code == 400
    assert r.json()["code"] == 10001


# ---------- 基准 OpenAPI 增量 ----------


def test_base_openapi_produces_diff(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        tid = _generate(
            client,
            base_openapi=yaml.safe_dump(BASE_SPEC, allow_unicode=True),
            generate_mode="fast",
        ).json()["task_id"]
        _wait_terminal(client, tid)
        payload = client.get(f"/api/v1/openapi/task/{tid}/result").json()

    doc = yaml.safe_load(payload["openapi"])
    assert "/legacy" in doc["paths"]  # 基准接口保留
    assert "/pets" in doc["paths"]  # 新接口合并
    diff = payload["diff"]
    assert diff is not None
    assert any("/pets" in str(p) for p in diff["added"])
    assert diff["deleted"] == []


def test_invalid_base_openapi_returns_10001(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        r = _generate(client, base_openapi="not: [valid")
    assert r.status_code == 400
    assert r.json()["code"] == 10001


def test_openapi_version_is_selectable(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        tid = _generate(client, openapi_version="3.1.0").json()["task_id"]
        _wait_terminal(client, tid)
        payload = client.get(f"/api/v1/openapi/task/{tid}/result").json()
    assert yaml.safe_load(payload["openapi"])["openapi"] == "3.1.0"


# ---------- 生成模式 ----------


def _force_validation_failure(monkeypatch) -> None:
    from openapi_agent.builder import validator
    from openapi_agent.core.errors import BusinessException

    def _boom(self):
        raise BusinessException(10005, "OpenAPI 文档规范校验失败", "forced")

    monkeypatch.setattr(validator.OpenApiValidator, "validate", _boom)


def test_fast_mode_keeps_validation_errors_in_report(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    _force_validation_failure(monkeypatch)
    with TestClient(app) as client:
        tid = _generate(client, generate_mode="fast").json()["task_id"]
        body = _wait_terminal(client, tid)
        assert body["status"] == "completed"
        payload = client.get(f"/api/v1/openapi/task/{tid}/result").json()
    assert payload["risk_report"]["validation_errors"][0]["message"] == "OpenAPI 文档规范校验失败"


def test_strict_mode_fails_on_validation_error(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    _force_validation_failure(monkeypatch)
    with TestClient(app) as client:
        tid = _generate(client, generate_mode="strict").json()["task_id"]
        body = _wait_terminal(client, tid)
    assert body["status"] == "failed"
    assert body["error_info"]["code"] == 10005


# ---------- 状态与进度上报 ----------


def test_progress_reported_on_completion(monkeypatch):
    monkeypatch.setattr(routes, "_llm_client", lambda: _fake_llm())
    with TestClient(app) as client:
        tid = _generate(client, generate_mode="fast").json()["task_id"]
        body = _wait_terminal(client, tid)
    assert body["status"] == "completed"
    assert body["progress"] == 100


def test_unknown_task_returns_10002():
    with TestClient(app) as client:
        r = client.get("/api/v1/openapi/task/task-missing/status")
    assert r.status_code == 404
    assert r.json()["code"] == 10002
