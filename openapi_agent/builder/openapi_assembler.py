import re

from openapi_agent.builder.schema_builder import build_responses, mark_inferred
from openapi_agent.model.intermediate_meta import ApiIntermediateMeta

OPENAPI_TYPES = {"string", "number", "integer", "boolean", "array", "object"}

DEFAULT_TAG = "默认分组"


class OpenApiAssembler:
    """根据中间元数据组装 OpenAPI 对象（设计文档 1.3 模块 4、2.2.2）。

    分组与接口名策略：
    - 接口名 `summary`：优先用元数据里的中文功能名，缺失时才回落到 `METHOD /path`；
    - 分组 `tag`：优先用元数据里的中文业务分组名，缺失时回落到路径首段，
      并在文档根节点声明 `tags`（保证 Swagger/Redoc 里有稳定的分组名与顺序）。
    """

    def __init__(
        self,
        metas: list[ApiIntermediateMeta],
        base_spec: dict | None = None,
        title: str = "Generated API",
        version: str = "1.0.0",
        openapi_version: str = "3.0.3",
    ):
        import copy

        self._metas = metas
        self._base_spec = copy.deepcopy(base_spec) if base_spec else None
        self._title = title
        self._version = version
        self._openapi_version = openapi_version

    def assemble(self) -> dict:
        doc: dict = self._base_spec or {}
        doc["openapi"] = self._openapi_version
        info = doc.setdefault("info", {})
        info.setdefault("title", self._title)
        info.setdefault("version", self._version)

        tags = self._document_tags()
        if tags:
            doc["tags"] = tags

        paths = doc.setdefault("paths", {})
        for meta in self._metas:
            path_item = paths.setdefault(meta.path, {})
            path_item[meta.method.lower()] = self._operation(meta)
        return doc

    # ---------- 分组 ----------

    def _document_tags(self) -> list[dict]:
        """按首次出现顺序声明文档级 tags（基于基准契约保留的分组也一并继承）。"""
        names: list[str] = []
        for meta in self._metas:
            tag = self._tag(meta)
            if tag not in names:
                names.append(tag)
        if not names:
            return []
        declared: dict[str, dict] = {}
        for existing in (self._base_spec or {}).get("tags") or []:
            if isinstance(existing, dict) and existing.get("name"):
                declared[existing["name"]] = existing
        result = [declared.get(name) or {"name": name} for name in names]
        # 保留基准契约里仍然被使用的分组（放在末尾），避免续写时丢掉说明
        for name, item in declared.items():
            if name not in names and self._base_tag_still_used(name):
                result.append(item)
        return result

    def _base_tag_still_used(self, name: str) -> bool:
        for path_item in ((self._base_spec or {}).get("paths") or {}).values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if isinstance(operation, dict) and name in (operation.get("tags") or []):
                    return True
        return False

    def _tag(self, meta: ApiIntermediateMeta) -> str:
        explicit = (meta.tag or "").strip()
        if explicit:
            return explicit
        segment = meta.path.strip("/").split("/")[0]
        return segment or DEFAULT_TAG

    # ---------- 操作 ----------

    def _operation(self, meta: ApiIntermediateMeta) -> dict:
        op: dict = {
            "summary": meta.summary or f"{meta.method} {meta.path}",
            "tags": [self._tag(meta)],
            "operationId": self._operation_id(meta),
            "responses": build_responses(meta.response_examples, meta.error_codes),
        }
        if meta.source:
            op["x-source"] = meta.source
        mark_inferred(op, meta.is_ai_infer, meta.is_conflict)

        parameters = [p for p in (self._parameter(i, meta) for i in meta.parameters) if p]
        if parameters:
            op["parameters"] = parameters
        body = self._request_body(meta.request_body, meta)
        if body:
            op["requestBody"] = body
        return op

    def _operation_id(self, meta: ApiIntermediateMeta) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", meta.path).strip("_")
        return f"{meta.method.lower()}_{slug}"

    def _parameter(self, raw: dict, meta: ApiIntermediateMeta) -> dict | None:
        name = raw.get("name")
        if not name:
            return None
        location = raw.get("in", "query")
        required = bool(raw.get("required", False)) or location == "path"
        parameter = {
            "name": name,
            "in": location,
            "required": required,
            "description": str(raw.get("description", "")),
            "schema": {"type": self._schema_type(raw)},
        }
        if raw.get("is_ai_infer") or raw.get("ai_infer"):
            parameter["x-ai-inferred"] = True
        if meta.is_ai_infer and not meta.source:
            parameter["x-ai-inferred"] = True
        return parameter

    def _schema_type(self, raw: dict) -> str:
        t = str(raw.get("type") or raw.get("data_type") or "string").lower()
        return t if t in OPENAPI_TYPES else "string"

    def _request_body(self, raw: dict | None, meta: ApiIntermediateMeta) -> dict | None:
        if not raw:
            return None
        schema = mark_inferred(self._to_schema(raw), meta.is_ai_infer, meta.is_conflict)
        return {
            "required": bool(raw.get("required", False)),
            "content": {"application/json": {"schema": schema}},
        }

    def _to_schema(self, raw: dict) -> dict:
        if raw.get("type") == "object" or "properties" in raw:
            schema = {"type": "object", "properties": raw.get("properties", {})}
            if raw.get("required"):
                schema["required"] = raw["required"]
            return schema
        fields = raw.get("fields")
        if isinstance(fields, list) and fields:
            properties = {}
            for field in fields:
                if isinstance(field, dict) and field.get("name"):
                    entry = {
                        "type": self._schema_type(field),
                        "description": str(field.get("description", "")),
                    }
                    if field.get("is_ai_infer") or field.get("ai_infer"):
                        entry["x-ai-inferred"] = True
                    properties[field["name"]] = entry
            schema = {"type": "object", "properties": properties}
            if raw.get("required"):
                schema["required"] = raw["required"]
            return schema
        return {"type": "object"}


__all__ = ["OpenApiAssembler", "OPENAPI_TYPES", "DEFAULT_TAG"]
