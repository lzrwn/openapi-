import time

from app.core.errors import BusinessException, ErrorCode


class FakeLlmClient:
    def __init__(self, responses: dict | None = None, defaults: dict | None = None, delay: float = 0.0):
        self.responses = responses or {}
        self.defaults = defaults or {}
        self.delay = delay
        self.calls: list[dict] = []

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
