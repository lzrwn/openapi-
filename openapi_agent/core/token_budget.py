"""Token 控制（设计文档 2.5 与 2.3.2）。

设计文档要求三层防护：
1. `MaterialPreprocessor.process()`：统计全部素材累计 token，超 TOTAL_MATERIAL_TOKEN_LIMIT 直接失败；
2. 分片控制单分片 token 大小；
3. `LlmClient.chat_json()`：单次请求（prompt + 分片 + 指令）调用前预校验。
另有两条兜底：`ENABLE_CONTEXT_TRUNCATE` 开启时按 token 尾部截断 / 摘要压缩，
以及捕获上游返回的上下文超限错误并归一为 10003。
"""

from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.prompt_templates import SUMMARY, render

TRUNCATE_WARNING = "\n【警告：文本已截断，内容可能丢失】"


def estimate_token(text: str) -> int:
    """粗略 token 估算：约 4 字符 = 1 token（中英混排的工程近似值）。"""
    if not text:
        return 0
    return max(1, len(text) // 4)

def truncate_text_by_token(text: str, max_token: int) -> tuple[str, bool]:
    """按 token 上限截断文本尾部，返回 (文本, 是否发生截断)。"""
    if max_token <= 0:
        raise BusinessException(ErrorCode.MATERIAL_ERROR, "素材解析错误或大小异常", "截断上限必须大于 0")
    if estimate_token(text) <= max_token:
        return text, False
    return text[: max_token * 4] + TRUNCATE_WARNING, True


def summary_fragment(llm_client, fragment_text: str, per_chunk_budget: int) -> tuple[str, bool]:
    """对超长分片做 LLM 摘要压缩（设计文档 2.5「输入摘要」）。

    仅在 ENABLE_CONTEXT_TRUNCATE=True 时被调用。
    入参是「单分片预算」，而不是整段 prompt 的预算：模板本身会占用一部分 token，
    因此这里只要求分片正文能放进预算，拼好后的 prompt 是否越界由 LlmClient 预校验兜底。
    """
    if estimate_token(fragment_text) > per_chunk_budget:
        raise BusinessException(
            ErrorCode.MATERIAL_ERROR,
            "分片过大无法摘要，请精简素材",
            f"分片约 {estimate_token(fragment_text)} token，超出单分片预算 {per_chunk_budget}",
        )
    prompt = render(SUMMARY, fragment_content=fragment_text)
    return llm_client.chat_raw(prompt), True


def is_context_overflow(exc: Exception) -> bool:
    """判断上游异常是否为上下文超限（而非普通网络/鉴权失败）。"""
    text = f"{exc}".lower()
    markers = (
        "context_length_exceeded",
        "context length",
        "maximum context",
        "max_context",
        "context limit",
        "too many tokens",
        "reduce the length",
        "prompt is too long",
    )
    return any(m in text for m in markers)
