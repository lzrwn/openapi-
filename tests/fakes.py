import time

from openapi_agent.core.errors import BusinessException, ErrorCode


class FakeLlmClient:
    """按 schema 注入应答的假 LLM；支持异常注入、延迟与纯文本调用。"""

    def __init__(
        self,
        responses: dict | None = None,
        defaults: dict | None = None,
        delay: float = 0.0,
        raw_responses: list | None = None,
    ):
        self.responses = responses or {}
        self.defaults = defaults or {}
        self.delay = delay
        self.raw_responses = list(raw_responses or [])
        self.calls: list[dict] = []
        self.raw_calls: list[str] = []

    def chat_json(self, system: str, user: str, schema):
        self.calls.append({"schema": schema.__name__, "system": system, "user": user})
        if self.delay:
            time.sleep(self.delay)
        queue = self.responses.get(schema.__name__)
        item = queue.pop(0) if queue else self.defaults.get(schema.__name__)
        if item is None:
            raise BusinessException(
                ErrorCode.LLM_ERROR, "fake llm: no scripted response", schema.__name__
            )
        if isinstance(item, Exception):
            raise item
        return schema.model_validate(item)

    def chat_raw(self, prompt: str) -> str:
        self.raw_calls.append(prompt)
        if self.delay:
            time.sleep(self.delay)
        if not self.raw_responses:
            raise BusinessException(ErrorCode.LLM_ERROR, "fake llm: no scripted raw response", "")
        item = self.raw_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
