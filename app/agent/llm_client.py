import json

import pydantic
from openai import OpenAI

from app.core.errors import BusinessException, ErrorCode

JSON_MODE = {"type": "json_object"}


class LlmClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model
        self._max_retries = max_retries

    def chat_json(self, system: str, user: str, schema: type[pydantic.BaseModel]) -> pydantic.BaseModel:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
                last_error = e
        raise BusinessException(
            ErrorCode.LLM_ERROR,
            "大模型服务调用失败或超时",
            str(last_error),
        )
