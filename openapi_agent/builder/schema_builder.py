"""把素材里的返回示例推导成 OpenAPI Schema（设计文档场景 3：产物可直接做 mock）。

推导是纯代码完成的确定性映射，不额外调用大模型（设计文档 2.5：避免元数据二次 token 膨胀）。
标注策略：无法从素材确证的字段带 `x-ai-inferred`，冲突项带 `x-conflict`。
"""

from typing import Any

SCALAR_TYPES = ("string", "number", "integer", "boolean")

_JSON_TYPE_MAP = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    type(None): "string",
}

SAMPLE_KEYS = ("value", "example", "default")


def schema_from_example(example: Any, depth: int = 0) -> dict:
    """由返回示例推导 Schema。示例本身来自素材，属于真实信息，不打 AI 推断标记。"""
    if depth > 6:
        return {"type": "object"}
    if isinstance(example, dict):
        properties = {
            str(key): schema_from_example(value, depth + 1) for key, value in example.items()
        }
        schema: dict = {"type": "object"}
        if properties:
            schema["properties"] = properties
        return schema
    if isinstance(example, list):
        if example:
            return {"type": "array", "items": schema_from_example(example[0], depth + 1)}
        return {"type": "array", "items": {"type": "object"}}
    for py_type, json_type in _JSON_TYPE_MAP.items():
        if isinstance(example, py_type):
            return {"type": json_type}
    return {"type": "string"}


def build_responses(response_examples: Any, error_codes: list | None = None) -> dict:
    """把 response_examples 组装成 responses 对象：200 带 schema，其余错误码只给描述。"""
    responses: dict[str, Any] = {}
    if response_examples:
        schema = schema_from_example(response_examples)
        responses["200"] = {
            "description": "OK",
            "content": {
                "application/json": {
                    "schema": schema,
                    "example": response_examples
                    if isinstance(response_examples, (dict, list))
                    else str(response_examples),
                }
            },
        }
    else:
        responses["200"] = {"description": "OK"}

    for item in error_codes or []:
        code, description = _split_error_code(item)
        if not code or code == "200":
            continue
        responses.setdefault(code, {"description": description})
    return responses


def _split_error_code(item: Any) -> tuple[str, str]:
    """支持 "400: 参数错误"、"400 参数错误"、"400"、{"code": 400, "description": "..."} 等形式。"""
    if isinstance(item, dict):
        code = item.get("code") or item.get("status")
        desc = item.get("description") or item.get("message") or item.get("desc") or ""
        return (str(code) if code is not None else ""), str(desc) or "Error"
    text = str(item).strip()
    if not text:
        return "", ""
    for sep in (":", "：", " ", "-", "—"):
        if sep in text:
            head, _, tail = text.partition(sep)
            if head.strip().isdigit():
                return head.strip(), tail.strip() or "Error"
    if text.isdigit():
        return text, "Error"
    return "", text


def mark_inferred(schema: dict, is_ai_infer: bool, is_conflict: bool) -> dict:
    """给 schema 顶层打上推断/冲突标记（设计文档 1.3 模块 4：标记 AI 推测内容）。"""
    if is_ai_infer:
        schema["x-ai-inferred"] = True
    if is_conflict:
        schema["x-conflict"] = True
    return schema


def mark_scalar_inferred(field: dict) -> dict:
    """参数/字段级推断标记。"""
    field["x-ai-inferred"] = True
    return field
