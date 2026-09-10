import logging
from pathlib import Path

from app.core.errors import BusinessException, ErrorCode
from app.preprocessing.file_parser import CODE_EXTS, FileParser
from app.preprocessing.splitter import recursive_split

logger = logging.getLogger(__name__)

MIN_CONTENT_LEN = 20


class MaterialPreprocessor:
    def __init__(
        self,
        files: list[str] | None = None,
        texts: list[str] | None = None,
        chunk_size: int = 1500,
        overlap: int = 150,
    ):
        self._files = files or []
        self._texts = texts or []
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._parser = FileParser()

    def process(self) -> list[dict]:
        chunks: list[dict] = []
        for path in self._files:
            try:
                segments = self._parser.parse(path)
            except Exception as e:
                logger.warning("素材解析失败，过滤脏数据 %s: %s", path, e)
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
        cleaned = [c for c in chunks if len(c["content"]) >= MIN_CONTENT_LEN]
        if not cleaned and (self._files or self._texts):
            raise BusinessException(
                ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", "无有效素材内容"
            )
        return cleaned

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
