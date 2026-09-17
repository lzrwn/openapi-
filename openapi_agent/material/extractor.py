import logging

from pydantic import BaseModel, Field

from openapi_agent.core.errors import BusinessException
from openapi_agent.core.prompt_templates import BASE_SYSTEM, EXTRACT, FUSE, render
from openapi_agent.model.intermediate_meta import ApiIntermediateMeta

logger = logging.getLogger(__name__)

ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


class RawEndpoint(BaseModel):
    path: str
    method: str = ""
    summary: str = ""
    tag: str = ""
    parameters: list = Field(default_factory=list)
    request_body: dict | None = None
    response_examples: list | dict | None = None
    error_codes: list = Field(default_factory=list)
    source_type: str = ""


class ExtractionResult(BaseModel):
    endpoints: list[RawEndpoint] = Field(default_factory=list)


class FusedEndpoint(BaseModel):
    path: str
    method: str
    summary: str = ""
    tag: str = ""
    parameters: list = Field(default_factory=list)
    request_body: dict | None = None
    response_examples: list | dict | None = None
    error_codes: list = Field(default_factory=list)
    source: str = ""
    is_conflict: bool = False
    is_ai_infer: bool = False
    notes: list[str] = Field(default_factory=list)


class MetaExtractor:
    def __init__(self, user_instruction: str = ""):
        self._user_instruction = user_instruction

    def extract(self, llm_client, chunks: list[dict] | None = None) -> list[ApiIntermediateMeta]:
        chunks = chunks or []
        raws: list[RawEndpoint] = []
        for chunk in chunks:
            raws.extend(self._extract_chunk(llm_client, chunk))
        return self._fuse(llm_client, raws)

    def _extract_chunk(self, llm_client, chunk: dict) -> list[RawEndpoint]:
        source_file = chunk.get("source_file") or "inline"
        source_type = chunk.get("source_type") or "unknown"
        # 来源标签由 preprocessor 用确定性规则给出，作为提示交给模型，
        # 避免模型自行猜测来源（多源冲突仲裁依赖 source_type 优先级）
        source_hint = f"{source_type}（文件: {source_file}）"
        user = render(
            EXTRACT,
            material_content=chunk.get("content", ""),
            user_instruction=self._user_instruction,
            source_hint=source_hint,
        )
        try:
            result = llm_client.chat_json(BASE_SYSTEM, user, ExtractionResult)
        except BusinessException as e:
            logger.warning("片段提取失败，跳过 %s: %s", source_file, e)
            return []
        endpoints = []
        for endpoint in result.endpoints:
            if not endpoint.path.strip():
                continue
            if not endpoint.source_type:
                endpoint.source_type = source_type
            endpoints.append(endpoint)
        return endpoints

    def _fuse(self, llm_client, raws: list[RawEndpoint]) -> list[ApiIntermediateMeta]:
        groups: dict[tuple[str, str], list[RawEndpoint]] = {}
        for r in raws:
            method = (r.method or "GET").upper()
            if method not in ALLOWED_METHODS:
                method = "GET"
            groups.setdefault((r.path.strip(), method), []).append(r)

        metas: list[ApiIntermediateMeta] = []
        for (path, method), items in groups.items():
            distinct = {json_dump(i) for i in items}
            sources = ",".join(sorted({i.source_type for i in items if i.source_type}))
            responses = [i.response_examples for i in items if i.response_examples]
            error_codes = _merge_error_codes(items)
            summaries = [i.summary for i in items if i.summary]
            tags = _first_tags(items)
            if len(items) == 1 or len(distinct) == 1:
                r = items[0]
                metas.append(
                    ApiIntermediateMeta(
                        path=path,
                        method=method,
                        summary=r.summary,
                        tag=r.tag,
                        parameters=r.parameters,
                        request_body=r.request_body,
                        response_examples=r.response_examples,
                        error_codes=error_codes,
                        source=sources or r.source_type,
                    )
                )
            else:
                metas.append(
                    self._fuse_group(
                        llm_client,
                        path,
                        method,
                        items,
                        sources,
                        responses,
                        error_codes,
                        summaries,
                        tags,
                    )
                )
        return metas

    def _fuse_group(
        self,
        llm_client,
        path: str,
        method: str,
        items: list[RawEndpoint],
        sources: str,
        responses: list,
        error_codes: list,
        summaries: list[str],
        tags: list[str],
    ) -> ApiIntermediateMeta:
        import json

        raw_meta_list = json.dumps(
            [i.model_dump() for i in items], ensure_ascii=False, indent=1
        )
        user = render(
            FUSE,
            raw_meta_list=raw_meta_list,
            user_instruction=self._user_instruction or "无",
        )
        fallback = ApiIntermediateMeta(
            path=path,
            method=method,
            summary=summaries[0] if summaries else "",
            tag=tags[0] if tags else "",
            parameters=items[0].parameters,
            request_body=items[0].request_body,
            response_examples=responses[0] if responses else None,
            error_codes=error_codes,
            source=sources,
            is_conflict=True,
            notes=["多源融合调用失败，保留第一份素材内容，请人工复核"],
        )
        try:
            fused = llm_client.chat_json(BASE_SYSTEM, user, FusedEndpoint)
        except BusinessException as e:
            logger.warning("融合失败 %s %s: %s", method, path, e)
            return fallback
        return ApiIntermediateMeta(
            path=path,
            method=method,
            summary=fused.summary or (summaries[0] if summaries else ""),
            tag=fused.tag or fallback.tag,
            parameters=fused.parameters,
            request_body=fused.request_body,
            response_examples=fused.response_examples if fused.response_examples else fallback.response_examples,
            error_codes=fused.error_codes or error_codes,
            source=fused.source or fallback.source,
            is_conflict=fused.is_conflict,
            is_ai_infer=fused.is_ai_infer,
            notes=fused.notes or fallback.notes,
        )


def json_dump(item: RawEndpoint) -> str:
    import json

    return json.dumps(item.model_dump(), ensure_ascii=False, sort_keys=True)


def _merge_error_codes(items: list[RawEndpoint]) -> list:
    """取各来源错误码定义的并集，去重后保持首次出现顺序。"""
    merged: list = []
    seen: set[str] = set()
    for item in items:
        for code in getattr(item, "error_codes", None) or []:
            key = json_dump_code(code)
            if key not in seen:
                seen.add(key)
                merged.append(code)
    return merged


def _first_tags(items: list[RawEndpoint]) -> list[str]:
    """各来源给出的业务分组名，去重后保持首次出现顺序。"""
    tags: list[str] = []
    for item in items:
        tag = (item.tag or "").strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def json_dump_code(code) -> str:
    import json

    return json.dumps(code, ensure_ascii=False, sort_keys=True, default=str)
