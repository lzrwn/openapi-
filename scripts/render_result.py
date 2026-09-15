"""从 res.json 渲染出 openapi.yaml，并打印风险报告与 diff。

用法：
    python scripts/render_result.py [res.json 路径]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _use_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def render(src: Path) -> Path:
    """把 res.json 里的 openapi 字符串落盘成 openapi.yaml。"""
    data = json.loads(src.read_text(encoding="utf-8"))
    out = src.with_name("openapi.yaml")
    out.write_text(data["openapi"], encoding="utf-8")
    return out


def main() -> int:
    _use_utf8_stdio()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "res.json"
    out = render(src)
    data = json.loads(src.read_text(encoding="utf-8"))

    print(f"已写入 {out}")
    print("风险报告：")
    print(json.dumps(data["risk_report"], ensure_ascii=False, indent=2))
    print(f"diff：{data['diff']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
