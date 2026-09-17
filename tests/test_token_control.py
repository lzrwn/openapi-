"""Token 控制三层防护与截断/摘要（设计文档 2.3.2 / 2.5）。"""

import pytest
from pydantic import BaseModel

from openapi_agent.config import Settings
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.llm_client import LlmClient
from openapi_agent.core.token_budget import (
    TRUNCATE_WARNING,
    estimate_token,
    is_context_overflow,
    summary_fragment,
    truncate_text_by_token,
)
from openapi_agent.material.preprocessor import MaterialPreprocessor
from tests.fakes import FakeLlmClient


class _Schema(BaseModel):
    endpoints: list = []


def _settings(**overrides) -> Settings:
    cfg = Settings()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# ---------- token_budget 基础函数 ----------


def test_estimate_token():
    assert estimate_token("") == 0
    assert estimate_token("abcd") == 1
    assert estimate_token("a" * 400) == 100


def test_truncate_text_by_token():
    text = "x" * 4000  # ≈1000 token
    out, truncated = truncate_text_by_token(text, 100)
    assert truncated is True
    assert out.endswith(TRUNCATE_WARNING)
    assert estimate_token(out) < 1000

    same, truncated2 = truncate_text_by_token("short", 100)
    assert same == "short"
    assert truncated2 is False


def test_truncate_rejects_bad_limit():
    with pytest.raises(BusinessException) as e:
        truncate_text_by_token("abc", 0)
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)


def test_is_context_overflow():
    assert is_context_overflow(Exception("This model's maximum context length is 8192 tokens"))
    assert is_context_overflow(Exception("context_length_exceeded"))
    assert not is_context_overflow(Exception("401 unauthorized"))


def test_summary_fragment_uses_chat_raw():
    llm = FakeLlmClient(raw_responses=["压缩后的摘要"])
    text, done = summary_fragment(llm, "很长的素材内容" * 50, 100000)
    assert text == "压缩后的摘要"
    assert done is True
    assert llm.raw_calls


def test_summary_fragment_rejects_oversized_fragment():
    llm = FakeLlmClient(raw_responses=["x"])
    with pytest.raises(BusinessException) as e:
        summary_fragment(llm, "y" * 4000, 10)  # 分片 ≈1000 token，超出预算 10
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)
    assert not llm.raw_calls


# ---------- 第 1 层：全局素材 token 上限 ----------


def test_preprocessor_rejects_total_token_over_limit():
    cfg = _settings(total_material_token_limit=50)
    pre = MaterialPreprocessor(texts=["接口描述" * 100], settings=cfg)
    with pytest.raises(BusinessException) as e:
        pre.process()
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)
    assert "token 上限" in e.value.message


def test_preprocessor_records_total_tokens():
    pre = MaterialPreprocessor(texts=["获取用户列表接口 GET /users，返回用户数据。"], settings=_settings())
    chunks = pre.process()
    assert pre.total_tokens > 0
    assert sum(estimate_token(c["content"]) for c in chunks) == pre.total_tokens


# ---------- 第 2 层：单分片大小 ----------


def test_preprocessor_rejects_oversized_chunk_when_truncate_disabled():
    cfg = _settings(per_chunk_token_limit=10, enable_context_truncate=False, chunk_size=4000)
    pre = MaterialPreprocessor(texts=["a" * 4000], settings=cfg)
    with pytest.raises(BusinessException) as e:
        pre.process()
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)
    assert "分片过大" in e.value.message


def test_preprocessor_summarizes_chunk_when_truncate_enabled():
    # 分片 ≈2000 token 超过触发阈值 1500 → 走摘要；摘要可用预算按模型上下文计算，因此能成功
    cfg = _settings(per_chunk_token_limit=1500, enable_context_truncate=True, chunk_size=8000)
    llm = FakeLlmClient(raw_responses=["摘要：GET /users"])
    pre = MaterialPreprocessor(texts=["a" * 8000], settings=cfg, llm_getter=lambda: llm)
    chunks = pre.process()
    assert chunks[0]["content"] == "摘要：GET /users"
    assert any("摘要压缩" in w for w in pre.warnings)
    assert llm.raw_calls


def test_preprocessor_falls_back_to_truncate_when_summary_rejects():
    # 预算被压到极小（模型上下文 400 token、预留 25% → 可用 300）；
    # 分片 ≈2000 token 超过可用输入预算 → 摘要函数拒绝 → 回退截断
    cfg = _settings(
        per_chunk_token_limit=100,
        enable_context_truncate=True,
        chunk_size=8000,
        model_max_context=400,
    )
    llm = FakeLlmClient(raw_responses=["unused"])
    pre = MaterialPreprocessor(texts=["b" * 8000], settings=cfg, llm_getter=lambda: llm)
    chunks = pre.process()
    assert TRUNCATE_WARNING in chunks[0]["content"]
    assert any("截断" in w for w in pre.warnings)
    assert not llm.raw_calls


# ---------- 第 3 层：单请求预算预校验 ----------


class _ExplodingOpenAI:
    def __init__(self, error: Exception):
        self.chat = self
        self.completions = self
        self._error = error
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise self._error


def _client_with_error(error: Exception, cfg: Settings) -> tuple[LlmClient, _ExplodingOpenAI]:
    client = LlmClient.__new__(LlmClient)
    client._model = "fake"
    client._max_retries = 2
    client._settings = cfg
    fake = _ExplodingOpenAI(error)
    client._client = fake
    return client, fake


def test_chat_json_rejects_request_over_budget():
    cfg = _settings(model_max_context=100, enable_context_truncate=False)
    client, fake = _client_with_error(RuntimeError("never called"), cfg)
    with pytest.raises(BusinessException) as e:
        client.chat_json("system", "u" * 4000, _Schema)
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)
    assert fake.calls == 0  # 预校验拦截，未真的发出请求


def test_chat_json_truncates_when_enabled():
    cfg = _settings(model_max_context=100, enable_context_truncate=True)

    class _OK:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.seen: list = []

        def create(self, **kwargs):
            self.seen = kwargs["messages"]
            return type(
                "R",
                (),
                {"choices": [type("C", (), {"message": type("M", (), {"content": '{"endpoints": []}'})()})()]},
            )()

    client, _ = _client_with_error(RuntimeError("unused"), cfg)
    ok = _OK()
    client._client = ok
    client.chat_json("system", "u" * 4000, _Schema)
    assert TRUNCATE_WARNING in ok.seen[-1]["content"]


def test_chat_json_maps_context_overflow_to_10003():
    cfg = _settings(model_max_context=100000, enable_context_truncate=False)
    client, fake = _client_with_error(
        RuntimeError("maximum context length is 8192 tokens"), cfg
    )
    with pytest.raises(BusinessException) as e:
        client.chat_json("system", "short", _Schema)
    assert int(e.value.code) == int(ErrorCode.MATERIAL_ERROR)
    assert fake.calls == 1  # 上游超限不重试


def test_chat_json_maps_other_errors_to_10004():
    cfg = _settings(model_max_context=100000)
    client, fake = _client_with_error(RuntimeError("connection reset"), cfg)
    with pytest.raises(BusinessException) as e:
        client.chat_json("system", "short", _Schema)
    assert int(e.value.code) == int(ErrorCode.LLM_ERROR)
    assert fake.calls == 3  # max_retries=2 → 共 3 次
