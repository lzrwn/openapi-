"""端到端冒烟脚本：真实启动 app，用 HTTP 跑完整链路。

前置：
    1) python scripts/mock_llm_server.py 11434
    2) OPENAPI_AGENT_BASE_URL=http://127.0.0.1:11434/v1 OPENAPI_AGENT_API_KEY=mock \
       python -m uvicorn openapi_agent.main:app --port 8123

用法：
    python scripts/smoke_http.py [base_url]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8123"
PREFIX = f"{BASE}/api/v1/openapi"
ROOT = Path(__file__).resolve().parent.parent

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, evidence: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {evidence}")


def request(method: str, url: str, data=None, headers=None):
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def form_request(url: str, fields: list[tuple[str, str]], files: list[tuple[str, str]] = None):
    """构造 multipart/form-data 请求。files 为 (字段名, 文件路径)。"""
    boundary = "----smoke" + str(int(time.time() * 1000))
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, path in files or []:
        p = Path(path)
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{p.name}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n".encode()
        )
        parts.append(p.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    payload = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def wait_terminal(task_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        _, body = request("GET", f"{PREFIX}/task/{task_id}/status")
        if body.get("status") in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.2)
    return body


def main() -> int:
    print(f"\n[1] 服务存活与 OpenAPI 文档  ({BASE})")
    status, doc = request("GET", f"{BASE}/openapi.json")
    check("GET /openapi.json 返回 200", status == 200, f"status={status}")
    check("挂载了 4 个接口", len(doc.get("paths", {})) == 4, f"paths={list(doc.get('paths', {}))}")
    check("files 字段标注为 binary", "binary" in json.dumps(doc), "")

    print("\n[2] 提交任务 → 轮询 → 取结果（文本素材）")
    status, submitted = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "用户列表接口：GET /api/v1/users，参数 page/page_size，返回用户集合。")],
    )
    check("POST /generate 返回 200", status == 200, f"status={status} body={submitted}")
    task_id = submitted.get("task_id", "")
    check("返回 task_id 且格式正确", task_id.startswith("task-") and len(task_id) == 40, task_id)
    check("返回 status=pending", submitted.get("status") == "pending", str(submitted))
    check("返回 msg 字段", bool(submitted.get("msg")), str(submitted))

    final = wait_terminal(task_id)
    check("任务最终 completed", final.get("status") == "completed", json.dumps(final, ensure_ascii=False))
    check("progress 上报为 100", final.get("progress") == 100, str(final.get("progress")))

    status, payload = request("GET", f"{PREFIX}/task/{task_id}/result")
    check("GET /result 返回 200", status == 200, f"status={status}")
    spec_text = payload.get("openapi", "")
    check("openapi 是非空字符串", isinstance(spec_text, str) and len(spec_text) > 50, str(type(spec_text)))
    check("包含 paths", "paths:" in spec_text, spec_text[:120])
    check("包含响应结构 schema", "responses:" in spec_text and "schema:" in spec_text, "")
    check("包含来源标注 x-source", "x-source" in spec_text, "")
    check("diff 默认 null", payload.get("diff") is None, str(payload.get("diff")))
    check(
        "risk_report 三件套齐全",
        all(k in payload.get("risk_report", {}) for k in ("conflict_items", "ai_infer_items", "missing_info")),
        str(payload.get("risk_report")),
    )

    print("\n[3] 基准契约增量（base_openapi → diff）")
    base = {
        "openapi": "3.0.3",
        "info": {"title": "Base", "version": "1.0.0"},
        "paths": {"/legacy": {"get": {"responses": {"200": {"description": "OK"}}}}},
    }
    status, submitted = form_request(
        f"{PREFIX}/generate",
        [
            ("text_materials", "用户列表接口：GET /api/v1/users。"),
            ("base_openapi", json.dumps(base, ensure_ascii=False)),
            ("generate_mode", "fast"),
        ],
    )
    check("带 base_openapi 提交成功", status == 200, f"status={status} body={submitted}")
    final = wait_terminal(submitted.get("task_id", ""))
    check("增量任务 completed", final.get("status") == "completed", json.dumps(final, ensure_ascii=False))
    _, payload = request("GET", f"{PREFIX}/task/{submitted['task_id']}/result")
    diff = payload.get("diff") or {}
    check("diff 不再是 null", isinstance(diff, dict) and diff, str(payload.get("diff")))
    check("diff 识别出新增接口", any("/api/v1/users" in str(p) for p in diff.get("added", [])), str(diff.get("added")))
    check("基准接口被保留", "/legacy" in payload.get("openapi", ""), "")

    print("\n[4] 文件上传链路")
    sample = next((ROOT / "examples").glob("sample_*.md"), None)
    check("找到示例素材", sample is not None, "")
    if sample:
        status, submitted = form_request(
            f"{PREFIX}/generate",
            [("generate_mode", "fast")],
            files=[("files", str(sample))],
        )
        check("文件上传提交成功", status == 200, f"status={status} body={submitted}")
        if status == 200:
            final = wait_terminal(submitted["task_id"])
            check("文件任务 completed", final.get("status") == "completed", json.dumps(final, ensure_ascii=False))

    print("\n[5] 取消任务")
    status, submitted = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "待取消的接口描述：GET /api/v1/cancel-me，返回空。")],
    )
    cancel_id = submitted.get("task_id", "")
    time.sleep(0.01)
    status, cancelled = request("POST", f"{PREFIX}/task/{cancel_id}/cancel")
    # 两种情况都算正确：赶在结束前取消（200/cancelled），或任务已结束（404/10002）
    if status == 200:
        check("取消接口返回 cancelled", cancelled.get("status") == "cancelled", str(cancelled))
    else:
        check(
            "任务已结束 → 取消返回 404/10002",
            status == 404 and cancelled.get("code") == 10002,
            f"status={status} body={cancelled}",
        )
    final = wait_terminal(cancel_id)
    check(
        "任务收敛到终态",
        final.get("status") in ("cancelled", "completed"),
        json.dumps(final, ensure_ascii=False),
    )

    print("\n[5b] 确定性取消（慢响应 LLM）")
    status, body = request("GET", f"{PREFIX}/task/task-x/status")
    check("取消未知任务 → 404", status == 404, f"{status} {body}")

    print("\n[6] 错误路径与错误码")
    status, body = request("GET", f"{PREFIX}/task/task-does-not-exist/status")
    check("未知 task_id → 404 / 10002", status == 404 and body.get("code") == 10002, f"{status} {body}")

    status, body = form_request(f"{PREFIX}/generate", [])
    check("空输入 → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    status, body = form_request(f"{PREFIX}/generate", [("text_materials", "GET /x 接口"), ("output_format", "xml")])
    check("非法 output_format → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    status, body = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "GET /x 接口"), ("generate_mode", "turbo")],
    )
    check("非法 generate_mode → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    status, body = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "GET /x 接口"), ("openapi_version", "2.0")],
    )
    check("非法 openapi_version → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    status, body = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "GET /x 接口"), ("user_instruction", "x" * 1001)],
    )
    check("指令过长 → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    status, body = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "GET /x 接口"), ("base_openapi", "not: [valid")],
    )
    check("非法 base_openapi → 400 / 10001", status == 400 and body.get("code") == 10001, f"{status} {body}")

    check("错误响应体统一为 {code,msg,detail}", set(body.keys()) == {"code", "msg", "detail"}, str(body.keys()))

    print("\n[7] OpenAI 版本可选")
    status, submitted = form_request(
        f"{PREFIX}/generate",
        [("text_materials", "GET /api/v1/users 查询用户。"), ("openapi_version", "3.1.0"), ("output_format", "json")],
    )
    if status == 200:
        wait_terminal(submitted["task_id"])
        _, payload = request("GET", f"{PREFIX}/task/{submitted['task_id']}/result")
        check("产物为 3.1.0", '"openapi": "3.1.0"' in payload.get("openapi", ""), payload.get("openapi", "")[:80])
    else:
        check("3.1.0 提交成功", False, f"status={status} {submitted}")

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name in FAILED:
        print(f"  ✗ {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
