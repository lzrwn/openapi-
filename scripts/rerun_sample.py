"""用 examples/sample_*.md 真实跑一次生成，覆盖仓库根目录的 res.json 与 openapi.yaml。

这一步需要真实的大模型调用，请先配置环境变量：

    OPENAPI_AGENT_BASE_URL   例如 https://api.openai.com/v1
    OPENAPI_AGENT_API_KEY
    OPENAPI_AGENT_MODEL      可选，默认 gpt-4o-mini

用法：
    python scripts/rerun_sample.py

产物写完后，README 的「输出示例」章节即可按该素材复现。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from render_result import render  # noqa: E402

TIMEOUT_SECONDS = 300.0
TERMINAL = ("completed", "failed", "cancelled")


def _use_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _sample_material() -> Path:
    candidates = sorted((ROOT / "examples").glob("sample_*.md"))
    if not candidates:
        raise SystemExit("未找到 examples/sample_*.md 素材文件")
    return candidates[0]


def _wait_terminal(client: TestClient, task_id: str) -> dict:
    deadline = time.time() + TIMEOUT_SECONDS
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/openapi/task/{task_id}/status").json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.5)
    raise SystemExit(f"任务未在 {TIMEOUT_SECONDS:.0f}s 内结束: {body}")


def main() -> int:
    _use_utf8_stdio()
    sample = _sample_material()
    print(f"素材：{sample.relative_to(ROOT)}")

    with TestClient(app) as client:
        with sample.open("rb") as fh:
            resp = client.post(
                "/api/v1/openapi/generate",
                files=[("files", (sample.name, fh, "text/markdown"))],
                data={"output_format": "yaml", "title": "Generated API", "version": "1.0.0"},
            )
        if resp.status_code != 200:
            raise SystemExit(f"提交任务失败 {resp.status_code}: {resp.text}")

        task_id = resp.json()["task_id"]
        print(f"task_id：{task_id}")

        status = _wait_terminal(client, task_id)
        if status["status"] != "completed":
            raise SystemExit(f"任务未成功：{json.dumps(status, ensure_ascii=False)}")

        payload = client.get(f"/api/v1/openapi/task/{task_id}/result").json()

    res_path = ROOT / "res.json"
    res_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {res_path.relative_to(ROOT)}")

    out = render(res_path)
    print(f"已写入 {out.relative_to(ROOT)}")
    print(f"接口数：{len(json.loads(payload['openapi']).get('paths', {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
