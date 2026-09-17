"""递归切块（内部工具，设计文档 2.2.1 未单列文件，由 preprocessor 承载）。"""


def recursive_split(
    text: str,
    chunk_size: int = 1500,
    overlap: int = 150,
    separators: list[str] | None = None,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    separators = separators or ["\n\n", "\n", "。", ". ", " ", ""]
    sep = separators[0]
    if sep == "" or sep not in text:
        step = max(chunk_size - overlap, 1)
        return [text[i : i + chunk_size] for i in range(0, len(text), step)]

    chunks: list[str] = []
    buf = ""
    for part in text.split(sep):
        piece = part + sep
        if len(piece) > chunk_size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(recursive_split(piece, chunk_size, overlap, separators[1:]))
        elif len(buf) + len(piece) > chunk_size:
            if buf:
                chunks.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]
