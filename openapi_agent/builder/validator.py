from openapi_agent.core.errors import BusinessException, ErrorCode

try:
    from openapi_spec_validator import validate as _validate
except ImportError:
    from openapi_spec_validator import validate_spec as _validate


class OpenApiValidator:
    def __init__(self, doc: dict):
        self._doc = doc

    def validate(self) -> None:
        try:
            _validate(self._doc)
        except Exception as e:
            raise BusinessException(ErrorCode.INTERNAL_ERROR, "OpenAPI 文档规范校验失败", str(e))
