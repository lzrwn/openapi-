import time

import yaml
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app
from tests.fakes import FakeLlmClient


def _wait_terminal(client: TestClient, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/openapi/task/{task_id}/status").json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内结束: {body}")


def test_generate_poll_result(monkeypatch):
    llm = FakeLlmClient(
        responses={"RiskScanResult": [{"missing_info": [], "conflict_items": [], "ai_infer_items": []}]},
        defaults={
            "ExtractionResult": {
                "endpoints": [
                    {
                        "path": "/users",
                        "method": "GET",
                        "parameters": [{"name": "page", "type": "integer"}],
                        "source_type": "markdown",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(routes, "_llm_client", lambda: llm)
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/openapi/generate",
            data={"texts": ["获取用户列表接口：GET /users，查询参数 page 整数，分页返回用户数据。"]},
        )
        assert r.status_code == 200
        tid = r.json()["task_id"]

        body = _wait_terminal(client, tid)
        assert body["status"] == "completed"

        r = client.get(f"/api/v1/openapi/task/{tid}/result")
        assert r.status_code == 200
        payload = r.json()
        doc = yaml.safe_load(payload["openapi"])
        assert "/users" in doc["paths"]
        assert doc["paths"]["/users"]["get"]["parameters"][0]["name"] == "page"
        assert "risk_report" in payload
        assert "diff" in payload and payload["diff"] is None


def test_generate_json_format_result(monkeypatch):
    import json

    llm = FakeLlmClient(
        defaults={
            "ExtractionResult": {
                "endpoints": [{"path": "/p", "method": "GET", "source_type": "markdown"}]
            }
        }
    )
    monkeypatch.setattr(routes, "_llm_client", lambda: llm)
    with TestClient(app) as client:
        tid = client.post(
            "/api/v1/openapi/generate",
            data={"texts": ["获取资源列表接口：GET /p，直接返回资源集合，无查询参数，便于测试。"], "output_format": "json"},
        ).json()["task_id"]
        _wait_terminal(client, tid)
        payload = client.get(f"/api/v1/openapi/task/{tid}/result").json()
        doc = json.loads(payload["openapi"])
        assert doc["paths"]["/p"]["get"]["responses"]["200"]["description"] == "OK"


def test_cancel_running_task(monkeypatch):
    llm = FakeLlmClient(delay=1.5, defaults={"ExtractionResult": {"endpoints": []}})
    monkeypatch.setattr(routes, "_llm_client", lambda: llm)
    with TestClient(app) as client:
        tid = client.post(
            "/api/v1/openapi/generate",
            data={"texts": ["这是一个足够长的测试文本，用来触发一次可被取消的异步生成任务流程验证。"]},
        ).json()["task_id"]

        time.sleep(0.3)
        r = client.post(f"/api/v1/openapi/task/{tid}/cancel")
        assert r.status_code == 200

        body = _wait_terminal(client, tid)
        assert body["status"] == "cancelled"

        r = client.get(f"/api/v1/openapi/task/{tid}/result")
        assert r.status_code == 400
        assert r.json()["code"] == 10001
