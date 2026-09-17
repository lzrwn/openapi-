"""系统配置：LLM 接入、Token 限额、文件限制、默认模式（设计文档 2.8.1）。

所有配置项均可用环境变量覆盖，前缀 openapi_agent 的大写形式，例如：
    OPENAPI_AGENT_MODEL_MAX_CONTEXT=64000
"""

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """运行期配置快照。每次构造都重新读取环境变量，便于测试注入。"""

    def __init__(self) -> None:
        # LLM 接入
        self.base_url = os.environ.get("OPENAPI_AGENT_BASE_URL", "")
        self.api_key = os.environ.get("OPENAPI_AGENT_API_KEY", "")
        self.model_name = os.environ.get("OPENAPI_AGENT_MODEL", "gpt-4o-mini")
        self.llm_timeout = float(os.environ.get("OPENAPI_AGENT_LLM_TIMEOUT", "60"))

        # Token 控制
        self.model_max_context = _int_env("OPENAPI_AGENT_MODEL_MAX_CONTEXT", 128000)
        self.total_material_token_limit = _int_env("OPENAPI_AGENT_TOTAL_MATERIAL_TOKEN_LIMIT", 100000)
        self.enable_context_truncate = _bool_env("OPENAPI_AGENT_ENABLE_CONTEXT_TRUNCATE", False)
        # 单分片 token 预算（设计文档 2.5 第 2 层）
        self.per_chunk_token_limit = _int_env("OPENAPI_AGENT_PER_CHUNK_TOKEN_LIMIT", 4000)
        # 单请求预算中留给「输出 + 模板」的比例
        self.prompt_reserve_ratio = float(os.environ.get("OPENAPI_AGENT_PROMPT_RESERVE_RATIO", "0.25"))

        # 入参与素材限制
        self.user_instruction_max_len = _int_env("OPENAPI_AGENT_USER_INSTRUCTION_MAX_LEN", 1000)
        self.max_upload_files = _int_env("OPENAPI_AGENT_MAX_UPLOAD_FILES", 10)
        self.max_file_size_mb = _int_env("OPENAPI_AGENT_MAX_FILE_SIZE_MB", 20)
        self.min_content_len = _int_env("OPENAPI_AGENT_MIN_CONTENT_LEN", 20)

        # 分片
        self.chunk_size = _int_env("OPENAPI_AGENT_CHUNK_SIZE", 1500)
        self.chunk_overlap = _int_env("OPENAPI_AGENT_CHUNK_OVERLAP", 150)

        # 任务
        self.async_worker_timeout = _int_env("OPENAPI_AGENT_ASYNC_WORKER_TIMEOUT", 300)

        # 生成
        self.default_generate_mode = os.environ.get("OPENAPI_AGENT_GENERATE_MODE", "strict")
        self.default_openapi_version = os.environ.get("OPENAPI_AGENT_OPENAPI_VERSION", "3.0.3")

        # 临时素材目录根路径；留空则用系统临时目录
        self.temp_root = os.environ.get("OPENAPI_AGENT_TEMP_ROOT", "")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()

GENERATE_MODES = ("strict", "fast")
OPENAPI_VERSIONS = ("3.0.3", "3.1.0")
OUTPUT_FORMATS = ("yaml", "json")
