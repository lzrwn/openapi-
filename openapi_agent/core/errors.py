from enum import IntEnum


class ErrorCode(IntEnum):
    INPUT_ERROR = 10001
    TASK_NOT_FOUND = 10002
    MATERIAL_ERROR = 10003
    LLM_ERROR = 10004
    INTERNAL_ERROR = 10005


class BusinessException(Exception):
    def __init__(self, code: int, message: str, detail: str | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)

    def __str__(self) -> str:
        if self.detail:
            return f"[{self.code}] {self.message}: {self.detail}"
        return f"[{self.code}] {self.message}"
