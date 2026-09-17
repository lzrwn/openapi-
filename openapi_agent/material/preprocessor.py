import logging
from pathlib import Path

from openapi_agent.config import settings as default_settings
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.token_budget import TRUNCATE_WARNING, estimate_token, summary_fragment
from openapi_agent.material.file_parser import CODE_EXTS, FileParser
from openapi_agent.material.splitter import recursive_split

logger = logging.getLogger(__name__)

MIN_CONTENT_LEN = 20


class MaterialPreprocessor:
    def __init__(
        self,
        files: list[str] | None = None,
        texts: list[str] | None = None,
        chunk_size: int | None = None,
        overlap: int | None = None,
        settings=None,
        llm_getter=None,
    ):
        self._settings = settings or default_settings
        self._files = files or []
        self._texts = texts or []
        self._chunk_size = chunk_size if chunk_size is not None else self._settings.chunk_size
        self._overlap = overlap if overlap is not None else self._settings.chunk_overlap
        self._parser = FileParser()
        self._llm_getter = llm_getter

        # 供上层读取的统计信息与风险提示
        self.total_tokens = 0
        self.warnings: list[str] = []

    # ---------- 主流程（设计文档 2.5：全局上限 → 分片 → 单分片大小） ----------

    def process(self) -> list[dict]:
        chunks: list[dict] = []
        for path in self._files:
            try:
                segments = self._parser.parse(path)
            except Exception as e:
                logger.warning("素材解析失败，过滤脏数据 %s: %s", path, e)
                self.warnings.append(f"素材解析失败已跳过: {Path(path).name}: {e}")
                continue
            source_file = Path(path).name
            for segment in segments:
                source_type = self._guess_source_type(path, segment)
                for piece in recursive_split(segment, self._chunk_size, self._overlap):
                    chunks.append(
                        {"content": piece, "source_file": source_file, "source_type": source_type}
                    )
        for text in self._texts:
            for piece in recursive_split(text, self._chunk_size, self._overlap):
                chunks.append(
                    {
                        "content": piece,
                        "source_file": "inline",
                        "source_type": self._guess_source_type("", piece),
                    }
                )

        cleaned = [c for c in chunks if len(c["content"]) >= self._settings.min_content_len]
        if not cleaned and (self._files or self._texts):
            raise BusinessException(
                ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", "无有效素材内容"
            )

        self.total_tokens = sum(estimate_token(c["content"]) for c in cleaned)
        self._check_total_limit()

        return [self._fit_chunk(c) for c in cleaned]

    def _check_total_limit(self) -> None:
        """第 1 层：全部素材累计 token 上限校验。"""
        limit = self._settings.total_material_token_limit
        if limit > 0 and self.total_tokens > limit:
            raise BusinessException(
                ErrorCode.MATERIAL_ERROR,
                "素材总量超出 token 上限",
                f"累计约 {self.total_tokens} token，超出 TOTAL_MATERIAL_TOKEN_LIMIT={limit}；"
                "请精简素材或调高上限",
            )

    def _fit_chunk(self, chunk: dict) -> dict:
        """第 2 层：保证单分片不超过单请求预算（超限时摘要或截断）。

        注意两个预算的区别：
        - `per_chunk_token_limit` 是「触发阈值」：分片超过它就认为太大；
        - 摘要/截断时用「模型上下文预算」作为上限，否则阈值与可行性会互相卡死。
        """
        trigger = self._per_chunk_budget()
        if trigger <= 0:
            return chunk
        content = chunk["content"]
        if estimate_token(content) <= trigger:
            return chunk

        if not self._settings.enable_context_truncate:
            # 关闭截断时严格失败，与 2.5「超限直接报错」一致
            raise BusinessException(
                ErrorCode.MATERIAL_ERROR,
                "单个素材分片过大",
                f"{chunk.get('source_file')} 约 {estimate_token(content)} token，"
                f"超出单分片预算 {trigger}；请调小 CHUNK_SIZE 或精简素材",
            )

        safe_input_max = self._safe_input_budget()
        try:
            summary, _ = summary_fragment(self._llm_getter(), content, safe_input_max)
            note = f"分片已摘要压缩: {chunk.get('source_file')}"
            new_content = summary
        except BusinessException:
            from openapi_agent.core.token_budget import truncate_text_by_token

            new_content, _ = truncate_text_by_token(content, safe_input_max)
            note = f"分片已按 token 截断: {chunk.get('source_file')}"
        logger.warning(note)
        self.warnings.append(note)
        return {**chunk, "content": new_content}

    def _safe_input_budget(self) -> int:
        """单次 LLM 输入可用的 token 预算（上下文窗口 - 输出/模板余量）。"""
        budget = self._settings.model_max_context
        if budget <= 0:
            return self._settings.per_chunk_token_limit or 1
        reserve = int(budget * self._settings.prompt_reserve_ratio)
        return max(budget - reserve, 1)

    def _per_chunk_budget(self) -> int:
        """单分片 token 预算（设计文档 2.5 第 2 层：控制单分片 token 大小）。"""
        limit = self._settings.per_chunk_token_limit
        if limit > 0:
            return limit
        budget = self._settings.model_max_context
        if budget <= 0:
            return 0
        reserve = int(budget * self._settings.prompt_reserve_ratio)
        return max(budget - reserve, 1)

    def _guess_source_type(self, path: str, content: str) -> str:
        ext = Path(path).suffix.lower()
        if ext == ".sql":
            return "sql"
        if ext in CODE_EXTS:
            return "code"
        name = Path(path).name.lower()
        if "test" in name:
            return "testcase"
        head = content[:400]
        if "curl " in head or head.lstrip().startswith("curl"):
            return "curl"
        return "markdown"


__all__ = ["MaterialPreprocessor", "MIN_CONTENT_LEN", "TRUNCATE_WARNING"]
