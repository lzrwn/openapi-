import json

import pydantic
from openai import OpenAI

from openapi_agent.config import settings as default_settings
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.token_budget import TRUNCATE_WARNING, estimate_token, is_context_overflow

JSON_MODE = {"type": "json_object"}


class LlmClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
        max_retries: int = 2,
        settings=None,
    ):
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model
        self._max_retries = max_retries
        self._settings = settings or default_settings

    # ---------- Token 预校验（设计文档 2.5 第 3 条） ----------

    def _check_budget(self, system: str, user: str) -> str:
        """调用前校验本次请求总 token；返回（可能被截断的）user 内容。"""
        budget = self._settings.model_max_context
        if budget <= 0:
            return user
        used = estimate_token(system) + estimate_token(user)
        if used <= budget:
            return user
        if self._settings.enable_context_truncate:
            allowed = max(budget - estimate_token(system), 1)
            truncated, _ = _truncate(user, allowed)
            return truncated
        raise BusinessException(
            ErrorCode.MATERIAL_ERROR,
            "上下文超限，素材过大",
            f"单次请求约 {used} token，超出 MODEL_MAX_CONTEXT={budget}；"
            "可开启 ENABLE_CONTEXT_TRUNCATE 或精简素材",
        )

    def _raise_llm_error(self, exc: Exception) -> None:
        """统一异常出口：上下文超限归一为 10003，其余为 10004。"""
        if is_context_overflow(exc):
            raise BusinessException(
                ErrorCode.MATERIAL_ERROR,
                "大模型上下文超限",
                str(exc),
            )
        raise BusinessException(ErrorCode.LLM_ERROR, "大模型服务调用失败或超时", str(exc))

    # ---------- 对外调用 ----------

    def chat_json(self, system: str, user: str, schema: type[pydantic.BaseModel]) -> pydantic.BaseModel:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": self._check_budget(system, user)},
        ]
        last_error: Exception | None = None
        for _ in range(self._max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format=JSON_MODE,
                    temperature=0.0,
                )
                content = resp.choices[0].message.content
                try:
                    return schema.model_validate_json(content)
                except pydantic.ValidationError:
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "上面的输出不符合要求的 JSON 结构，"
                            "请严格按照要求只输出 JSON，不要输出任何其他内容。",
                        }
                    )
                    last_error = ValueError(f"invalid json schema output: {content[:200]}")
            except BusinessException:
                raise
            except Exception as e:
                if is_context_overflow(e):
                    # 模型侧返回超限：兜底归一为 10003，不再盲目重试
                    self._raise_llm_error(e)
                last_error = e
        self._raise_llm_error(last_error or RuntimeError("unknown llm error"))

    def chat_raw(self, prompt: str) -> str:
        """不带 JSON Mode 的纯文本调用（设计文档 2.5 摘要链路使用）。"""
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            self._raise_llm_error(e)
            raise  # pragma: no cover - _raise_llm_error 必定抛出


def _truncate(text: str, max_token: int) -> tuple[str, bool]:
    from openapi_agent.core.token_budget import truncate_text_by_token

    return truncate_text_by_token(text, max_token)


__all__ = ["LlmClient", "JSON_MODE", "TRUNCATE_WARNING"]
