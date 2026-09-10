import json
import logging

from pydantic import BaseModel, Field

from app.agent.models import ApiIntermediateMeta
from app.agent.prompts import load_prompt, render
from app.core.errors import BusinessException

logger = logging.getLogger(__name__)

ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


class RawEndpoint(BaseModel):
    path: str
    method: str = ""
    summary: str = ""
    parameters: list = Field(default_factory=list)
    request_body: dict | None = None
    response_examples: list | dict | None = None
    source_type: str = ""


class ExtractionResult(BaseModel):
    endpoints: list[RawEndpoint] = Field(default_factory=list)


class FusedEndpoint(BaseModel):
    path: str
    method: str
    parameters: list = Field(default_factory=list)
    request_body: dict | None = None
    source: str = ""
    is_conflict: bool = False
    is_ai_infer: bool = False
    notes: list[str] = Field(default_factory=list)


class MetaExtractor:
    def __init__(self, user_instruction: str = ""):
        self._user_instruction = user_instruction
        self._base = load_prompt("base_system")
        self._extract_tpl = load_prompt("extract")
        self._fuse_tpl = load_prompt("fuse")

    def extract(self, llm_client, chunks: list[dict] | None = None) -> list[ApiIntermediateMeta]:
        chunks = chunks or []
        raws: list[RawEndpoint] = []
        for chunk in chunks:
            raws.extend(self._extract_chunk(llm_client, chunk))
        return self._fuse(llm_client, raws)

    def _extract_chunk(self, llm_client, chunk: dict) -> list[RawEndpoint]:
        system = self._base
        user = render(
            self._extract_tpl,
            material_content=chunk.get("content", ""),
            user_instruction=self._user_instruction,
        )
        try:
            result = llm_client.chat_json(system, user, ExtractionResult)
        except BusinessException as e:
            logger.warning("片段提取失败，跳过 %s: %s", chunk.get("source_file"), e)
            return []
        return [e for e in result.endpoints if e.path.strip()]

    def _fuse(self, llm_client, raws: list[RawEndpoint]) -> list[ApiIntermediateMeta]:
        groups: dict[tuple[str, str], list[RawEndpoint]] = {}
        for r in raws:
            method = (r.method or "GET").upper()
            if method not in ALLOWED_METHODS:
                method = "GET"
            groups.setdefault((r.path.strip(), method), []).append(r)

        metas: list[ApiIntermediateMeta] = []
        for (path, method), items in groups.items():
            distinct = {
                json.dumps(i.model_dump(), ensure_ascii=False, sort_keys=True) for i in items
            }
            if len(items) == 1 or len(distinct) == 1:
                r = items[0]
                sources = sorted({i.source_type for i in items if i.source_type})
                metas.append(
                    ApiIntermediateMeta(
                        path=path,
                        method=method,
                        parameters=r.parameters,
                        request_body=r.request_body,
                        source=",".join(sources) or r.source_type,
                    )
                )
            else:
                metas.append(self._fuse_group(llm_client, path, method, items))
        return metas

    def _fuse_group(self, llm_client, path: str, method: str, items: list[RawEndpoint]) -> ApiIntermediateMeta:
        raw_meta_list = json.dumps(
            [i.model_dump() for i in items], ensure_ascii=False, indent=1
        )
        system = self._base
        user = render(
            self._fuse_tpl,
            raw_meta_list=raw_meta_list,
            user_instruction=self._user_instruction or "无",
        )
        fallback = ApiIntermediateMeta(
            path=path,
            method=method,
            parameters=items[0].parameters,
            request_body=items[0].request_body,
            source=",".join(sorted({i.source_type for i in items if i.source_type})),
            is_conflict=True,
            notes=["多源融合调用失败，保留第一份素材内容，请人工复核"],
        )
        try:
            fused = llm_client.chat_json(system, user, FusedEndpoint)
        except BusinessException as e:
            logger.warning("融合失败 %s %s: %s", method, path, e)
            return fallback
        return ApiIntermediateMeta(
            path=path,
            method=method,
            parameters=fused.parameters,
            request_body=fused.request_body,
            source=fused.source or fallback.source,
            is_conflict=fused.is_conflict,
            is_ai_infer=fused.is_ai_infer,
            notes=fused.notes or fallback.notes,
        )
