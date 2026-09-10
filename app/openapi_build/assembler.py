import copy
import re
from typing import Any

from app.agent.models import ApiIntermediateMeta

OPENAPI_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


class OpenApiAssembler:
    def __init__(
        self,
        metas: list[ApiIntermediateMeta],
        base_spec: dict | None = None,
        title: str = "Generated API",
        version: str = "1.0.0",
    ):
        self._metas = metas
        self._base_spec = copy.deepcopy(base_spec) if base_spec else None
        self._title = title
        self._version = version

    def assemble(self) -> dict:
        doc: dict = self._base_spec or {}
        doc["openapi"] = "3.0.3"
        info = doc.setdefault("info", {})
        info.setdefault("title", self._title)
        info.setdefault("version", self._version)
        paths = doc.setdefault("paths", {})
        for meta in self._metas:
            path_item = paths.setdefault(meta.path, {})
            path_item[meta.method.lower()] = self._operation(meta)
        return doc

    def _operation(self, meta: ApiIntermediateMeta) -> dict:
        op: dict[str, Any] = {
            "summary": f"{meta.method} {meta.path}",
            "tags": [meta.path.strip("/").split("/")[0] or "default"],
            "operationId": self._operation_id(meta),
            "responses": {"200": {"description": "OK"}},
        }
        parameters = [p for p in (self._parameter(i) for i in meta.parameters) if p]
        if parameters:
            op["parameters"] = parameters
        body = self._request_body(meta.request_body)
        if body:
            op["requestBody"] = body
        return op

    def _operation_id(self, meta: ApiIntermediateMeta) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", meta.path).strip("_")
        return f"{meta.method.lower()}_{slug}"

    def _parameter(self, raw: dict) -> dict | None:
        name = raw.get("name")
        if not name:
            return None
        location = raw.get("in", "query")
        required = bool(raw.get("required", False)) or location == "path"
        return {
            "name": name,
            "in": location,
            "required": required,
            "description": str(raw.get("description", "")),
            "schema": {"type": self._schema_type(raw)},
        }

    def _schema_type(self, raw: dict) -> str:
        t = str(raw.get("type") or raw.get("data_type") or "string").lower()
        return t if t in OPENAPI_TYPES else "string"

    def _request_body(self, raw: dict | None) -> dict | None:
        if not raw:
            return None
        return {
            "required": bool(raw.get("required", False)),
            "content": {"application/json": {"schema": self._to_schema(raw)}},
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
                    properties[field["name"]] = {
                        "type": self._schema_type(field),
                        "description": str(field.get("description", "")),
                    }
            return {"type": "object", "properties": properties}
        return {"type": "object"}
