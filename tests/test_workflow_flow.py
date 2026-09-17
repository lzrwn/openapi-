from openapi_agent.material.extractor import MetaExtractor
from openapi_agent.core.agent_workflow import AgentWorkflow
from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.material.preprocessor import MaterialPreprocessor
from tests.fakes import FakeLlmClient

RISK_EMPTY = {"missing_info": [], "conflict_items": [], "ai_infer_items": []}


def test_workflow_happy_path():
    llm = FakeLlmClient(
        responses={
            "ExtractionResult": [
                {
                    "endpoints": [
                        {
                            "path": "/pets",
                            "method": "POST",
                            "request_body": {
                                "fields": [{"name": "name", "type": "string", "description": "名字"}]
                            },
                            "source_type": "markdown",
                        }
                    ]
                }
            ],
            "RiskScanResult": [
                {"missing_info": ["LLM扫描：/pets 缺少响应定义"], "conflict_items": [], "ai_infer_items": []}
            ],
        },
        defaults={"ExtractionResult": {"endpoints": []}},
    )
    pre = MaterialPreprocessor(texts=["创建宠物接口：POST /pets，请求体字段 name（字符串，必填）。"])
    metas, result = AgentWorkflow().run(llm, pre, MetaExtractor(user_instruction=""))

    assert [m.path for m in metas] == ["/pets"]
    doc = result["openapi"]
    assert doc["paths"]["/pets"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]["name"]["type"] == "string"
    assert result["diff"] is None
    assert not result["risk_report"].get("validation_errors")
    issues = result["risk_report"]["missing_info"]
    assert any("LLM扫描" in i["issue"] for i in issues)
    assert any(i.get("scope") == "global" for i in issues)
    assert llm.calls[0]["schema"] == "ExtractionResult"
    assert "永久固定规则" in llm.calls[0]["system"]
    assert "创建宠物接口" in llm.calls[0]["user"]


def test_multi_source_fusion_marks_conflict():
    llm = FakeLlmClient(
        responses={
            "ExtractionResult": [
                {
                    "endpoints": [
                        {
                            "path": "/pets",
                            "method": "GET",
                            "parameters": [{"name": "limit", "type": "integer"}],
                            "source_type": "code",
                        }
                    ]
                },
                {
                    "endpoints": [
                        {
                            "path": "/pets",
                            "method": "GET",
                            "parameters": [
                                {"name": "limit", "type": "integer"},
                                {"name": "q", "type": "string"},
                            ],
                            "source_type": "markdown",
                        }
                    ]
                },
            ],
            "FusedEndpoint": [
                {
                    "path": "/pets",
                    "method": "GET",
                    "parameters": [{"name": "limit", "type": "integer"}, {"name": "q", "type": "string"}],
                    "source": "code,markdown",
                    "is_conflict": True,
                    "is_ai_infer": False,
                    "notes": ["q 参数仅文档提及"],
                }
            ],
            "RiskScanResult": [RISK_EMPTY],
        },
        defaults={"ExtractionResult": {"endpoints": []}},
    )
    pre = MaterialPreprocessor(
        texts=[
            "源码注释：GET /pets 查询宠物列表，参数 limit 整数。",
            "接口文档：GET /pets 宠物列表接口，参数 limit 整数、q 字符串。",
        ]
    )
    metas, result = AgentWorkflow().run(llm, pre, MetaExtractor(user_instruction="过滤调试接口"))

    assert len(metas) == 1
    assert metas[0].is_conflict is True
    assert [p["name"] for p in metas[0].parameters] == ["limit", "q"]
    fuse_calls = [c for c in llm.calls if c["schema"] == "FusedEndpoint"]
    assert len(fuse_calls) == 1
    assert "code" in fuse_calls[0]["user"]
    assert "markdown" in fuse_calls[0]["user"]
    assert "过滤调试接口" in fuse_calls[0]["user"]
    assert result["risk_report"]["conflict_items"][0]["path"] == "/pets"


def test_source_label_is_passed_to_extraction_prompt():
    """preprocessor 的确定性来源标签必须进入提取 Prompt，不能只靠模型猜。"""
    for expected_type, payload in (
        ("sql", {"path": "/u", "method": "GET", "source_type": "sql"}),
        ("code", {"path": "/u", "method": "GET", "source_type": "code"}),
    ):
        llm = FakeLlmClient(defaults={"ExtractionResult": {"endpoints": [payload]}})
        extractor = MetaExtractor()
        metas = extractor.extract(
            llm,
            chunks=[
                {
                    "content": "接口定义片段：GET /u，返回用户集合，字段说明见素材。",
                    "source_file": f"demo.{expected_type}",
                    "source_type": expected_type,
                }
            ],
        )
        prompt = llm.calls[0]["user"]
        assert expected_type in prompt
        assert f"demo.{expected_type}" in prompt
        assert metas[0].source == expected_type


def test_extraction_failure_skips_chunk():
    llm = FakeLlmClient(
        responses={"ExtractionResult": [BusinessException(ErrorCode.LLM_ERROR, "超时")]},
    )
    pre = MaterialPreprocessor(
        texts=[
            "文本一：创建资源接口 POST /a，字段 x 为字符串且必填。",
            "文本二：删除资源接口 DELETE /a，按 id 删除指定资源。",
        ]
    )
    metas, result = AgentWorkflow().run(llm, pre, MetaExtractor())

    assert metas == []
    assert result["openapi"]["paths"] == {}
    assert not result["risk_report"].get("validation_errors")


def test_fusion_failure_falls_back_to_first_source():
    llm = FakeLlmClient(
        responses={
            "ExtractionResult": [
                {
                    "endpoints": [
                        {
                            "path": "/a",
                            "method": "POST",
                            "request_body": {"fields": [{"name": "x", "type": "string"}]},
                            "source_type": "curl",
                        }
                    ]
                },
                {
                    "endpoints": [
                        {
                            "path": "/a",
                            "method": "POST",
                            "request_body": {"fields": [{"name": "x", "type": "integer"}]},
                            "source_type": "markdown",
                        }
                    ]
                },
            ],
            "RiskScanResult": [RISK_EMPTY],
        },
    )
    pre = MaterialPreprocessor(
        texts=[
            "真实请求样例：curl -X POST /a 提交字段 x，值为字符串类型。",
            "接口文档：POST /a 创建资源，字段 x 类型为整型数字。",
        ]
    )
    metas, _ = AgentWorkflow().run(llm, pre, MetaExtractor())

    assert len(metas) == 1
    assert metas[0].is_conflict is True
    assert metas[0].request_body["fields"][0]["name"] == "x"
    assert any("融合" in n for n in metas[0].notes)


def test_risk_scan_failure_keeps_deterministic_report():
    llm = FakeLlmClient(
        responses={
            "ExtractionResult": [
                {"endpoints": [{"path": "/b", "method": "GET", "source_type": "markdown"}]}
            ]
        }
    )
    pre = MaterialPreprocessor(
        texts=["这是一个较长的接口描述文本：获取用户列表接口 GET /b，该接口无需任何参数即可调用。"]
    )
    metas, result = AgentWorkflow().run(llm, pre, MetaExtractor())

    assert len(metas) == 1
    report = result["risk_report"]
    assert report["missing_info"]
    assert any("缺少查询参数" in i["issue"] for i in report["missing_info"])
    assert any(i.get("scope") == "global" for i in report["missing_info"])
