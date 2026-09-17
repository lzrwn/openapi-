"""LLM 客户端装配（可被测试替换）。"""

from openapi_agent.config import settings as default_settings
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.llm_client import LlmClient


def build_llm_client(settings=None) -> LlmClient:
    cfg = settings or default_settings
    if not cfg.base_url or not cfg.api_key:
        raise BusinessException(
            ErrorCode.INTERNAL_ERROR,
            "缺少大模型服务配置",
            "请设置环境变量 OPENAPI_AGENT_BASE_URL / OPENAPI_AGENT_API_KEY",
        )
    return LlmClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model_name,
        timeout=cfg.llm_timeout,
        settings=cfg,
    )
