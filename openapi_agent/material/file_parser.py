import zipfile
from pathlib import Path

TEXT_EXTS = {".md", ".markdown", ".txt", ".rst", ".csv", ".log", ".curl", ".http"}
CODE_EXTS = {
    ".py", ".java", ".go", ".js", ".ts", ".jsx", ".tsx", ".php", ".rb",
    ".rs", ".c", ".cpp", ".cs", ".kt", ".swift", ".vue",
}
SQL_EXTS = {".sql"}
SPEC_EXTS = {".yaml", ".yml", ".json"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
ZIP_EXTS = {".zip"}
PARSABLE_EXTS = TEXT_EXTS | CODE_EXTS | SQL_EXTS | SPEC_EXTS | IMAGE_EXTS | ZIP_EXTS


class FileParser:
    def parse(self, path: str) -> list[str]:
        p = Path(path)
        ext = p.suffix.lower()
        if ext in SPEC_EXTS:
            return self._parse_spec(p)
        if ext in TEXT_EXTS or ext in CODE_EXTS or ext in SQL_EXTS:
            return [p.read_text(encoding="utf-8", errors="replace")]
        if ext in ZIP_EXTS:
            return self._parse_zip(p)
        if ext in IMAGE_EXTS:
            return self._parse_image(p)
        raise ValueError(f"不支持的文件类型: {p.name}")

    def _parse_spec(self, p: Path) -> list[str]:
        import json

        import yaml

        text = p.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
            if isinstance(data, dict):
                return [json.dumps(data, ensure_ascii=False, indent=1)]
        except Exception:
            pass
        return [text]

    def _parse_zip(self, p: Path) -> list[str]:
        segments: list[str] = []
        with zipfile.ZipFile(p) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                inner_ext = Path(info.filename).suffix.lower()
                if inner_ext not in PARSABLE_EXTS or inner_ext in ZIP_EXTS or inner_ext in IMAGE_EXTS:
                    continue
                try:
                    raw = zf.read(info).decode("utf-8", errors="replace")
                except Exception:
                    continue
                segments.append(f"[压缩包内文件: {info.filename}]\n{raw}")
        if not segments:
            raise ValueError(f"压缩包内无可解析的文本文件: {p.name}")
        return segments

    def _parse_image(self, p: Path) -> list[str]:
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise ValueError(f"图片需要 OCR 支持，请安装 paddleocr: {p.name}") from e
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(str(p), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                lines.append(item[1][0])
        text = "\n".join(lines)
        if not text.strip():
            raise ValueError(f"OCR 未识别出文本: {p.name}")
        return [text]
