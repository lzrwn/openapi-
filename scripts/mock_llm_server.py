"""本地假的 OpenAI 兼容服务，用于在没有真实模型/密钥时跑通全链路。

启动：
    python scripts/mock_llm_server.py [port]
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXTRACT_PAYLOAD = {
    "endpoints": [
        {
            "path": "/api/v1/users",
            "method": "GET",
            "summary": "查询用户列表",
            "parameters": [
                {"name": "page", "in": "query", "type": "integer", "description": "页码"},
                {"name": "page_size", "in": "query", "type": "integer", "description": "每页条数"},
            ],
            "request_body": None,
            "response_examples": {"total": 2, "items": [{"id": "u_1", "nickname": "张三"}]},
            "error_codes": ["400: 参数错误", "401: 未登录"],
            "source_type": "markdown",
        },
        {
            "path": "/api/v1/users",
            "method": "POST",
            "summary": "创建用户",
            "parameters": [],
            "request_body": {
                "fields": [
                    {"name": "nickname", "type": "string", "description": "昵称"},
                    {"name": "age", "type": "integer", "description": "年龄"},
                ]
            },
            "response_examples": {"id": "u_2", "nickname": "李四"},
            "error_codes": [],
            "source_type": "curl",
        },
        {
            "path": "/api/v1/internal/debug",
            "method": "GET",
            "summary": "内部调试接口",
            "parameters": [],
            "request_body": None,
            "response_examples": None,
            "error_codes": [],
            "source_type": "code",
        },
    ]
}

RISK_PAYLOAD = {
    "missing_info": ["POST /api/v1/users 未给出重复昵称的错误码"],
    "conflict_items": [],
    "ai_infer_items": [],
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        text = json.dumps(body.get("messages", []), ensure_ascii=False)
        if "风险扫描" in text or "final_meta_list" in text:
            payload = RISK_PAYLOAD
        else:
            payload = EXTRACT_PAYLOAD

        data = json.dumps(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": body.get("model", "mock"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静默
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11434
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock llm listening on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
