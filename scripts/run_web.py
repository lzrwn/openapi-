"""启动脚本：从 .env 读取配置后启动 Web 界面。

用法：
    python scripts/run_web.py

配置来源（优先级从高到低）：
1. 已存在的系统环境变量
2. 仓库根目录的 .env 文件

.env 示例见 .env.example。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> list[str]:
    """把 .env 写入 os.environ（不覆盖已存在的系统环境变量），返回加载的键名。

    兼容 Windows 记事本 / PowerShell `Set-Content -Encoding UTF8` 写入的 BOM：
    这里会剥掉 BOM 与零宽字符，否则第一个变量名会变成 `\\ufeffOPENAPI_AGENT_BASE_URL` 而被静默忽略。
    """
    import os

    env_file = ROOT / ".env"
    if not env_file.exists():
        return []
    loaded: list[str] = []
    text = env_file.read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff\u200b")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lstrip("\ufeff\u200b")
        value = value.strip().lstrip("\ufeff\u200b").strip('"').strip("'")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    loaded = _load_env()

    # 必须在导入应用之前完成环境变量注入：Settings 在模块导入时读取环境变量
    from openapi_agent.config import settings  # noqa: E402

    print(f"已从 .env 载入 {len(loaded)} 项: {', '.join(loaded) if loaded else '（无）'}")
    if not settings.base_url or not settings.api_key:
        print("\n[启动失败] 缺少大模型配置，请先创建 .env（参考 .env.example）：")
        print("  OPENAPI_AGENT_BASE_URL=https://api.openai.com/v1")
        print("  OPENAPI_AGENT_API_KEY=sk-xxxxxx")
        return 1

    print(f"模型服务 : {settings.base_url}")
    print(f"模型名称 : {settings.model_name}")
    print(f"密钥     : {'*' * 8}{settings.api_key[-4:] if len(settings.api_key) > 4 else ''}")

    import uvicorn

    host = os.environ.get("OPENAPI_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENAPI_AGENT_PORT", "8000"))
    print(f"接口文档 : http://{host}:{port}/docs")
    uvicorn.run("openapi_agent.main:app", host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
