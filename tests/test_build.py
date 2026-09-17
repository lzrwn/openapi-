from openapi_agent.model.intermediate_meta import ApiIntermediateMeta
from openapi_agent.builder.openapi_assembler import OpenApiAssembler
from openapi_agent.builder.diff_helper import DiffHelper
from openapi_agent.builder.validator import OpenApiValidator
from openapi_agent.material.splitter import recursive_split
from openapi_agent.report.risk_report_builder import RiskReportBuilder


def _metas() -> list[ApiIntermediateMeta]:
    return [
        ApiIntermediateMeta(
            path="/orders",
            method="POST",
            request_body={"fields": [{"name": "sku_id", "type": "string", "description": "商品ID"}]},
            source="markdown",
        ),
        ApiIntermediateMeta(
            path="/orders/{id}",
            method="GET",
            parameters=[{"name": "id", "in": "path", "type": "string"}],
            source="code",
            is_conflict=True,
            notes=["多源字段定义不一致"],
        ),
    ]


def test_assemble_produces_valid_openapi():
    doc = OpenApiAssembler(_metas(), title="T", version="0.1").assemble()
    assert doc["openapi"] == "3.0.3"
    assert "/orders" in doc["paths"]
    assert "post" in doc["paths"]["/orders"]
    assert doc["paths"]["/orders"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["properties"]["sku_id"]["type"] == "string"
    OpenApiValidator(doc).validate()


def test_diff_categories():
    old = {"a": 1, "b": 2}
    new = {"a": 1, "b": 3, "c": 4}
    d = DiffHelper(old, new).diff()
    assert any("c" in str(p) for p in d["added"])
    assert any("b" in str(k) for k in d["modified"])
    assert d["deleted"] == []


def test_risk_report_flags():
    report = RiskReportBuilder(_metas()).build()
    assert report["conflict_items"][0]["path"] == "/orders/{id}"
    assert report["ai_infer_items"] == []
    assert any("响应结构" in i["issue"] for i in report["missing_info"] if i.get("scope") == "global")
    # 两个接口都没有返回示例 → 逐接口也提示缺少响应结构
    assert sum(1 for i in report["missing_info"] if i.get("issue") == "缺少响应结构定义") == 2


def test_risk_report_respects_response_examples():
    metas = _metas()
    metas[0].response_examples = {"order_id": "1", "status": "created"}
    report = RiskReportBuilder(metas).build()
    # 已有响应示例的接口不再报缺失；没有示例的接口仍然报
    per_endpoint = [i for i in report["missing_info"] if i.get("issue") == "缺少响应结构定义"]
    assert [i["path"] for i in per_endpoint] == ["/orders/{id}"]
    # 至少有一个接口有响应结构 → 不再输出「响应结构」的全局告警
    global_issues = [i["issue"] for i in report["missing_info"] if i.get("scope") == "global"]
    assert not any("响应结构" in issue for issue in global_issues)


# ---------- 中文分组（tag）与中文接口名（summary） ----------


def _tagged_metas() -> list[ApiIntermediateMeta]:
    return [
        ApiIntermediateMeta(
            path="/api/v1/products",
            method="GET",
            summary="查询文件列表",
            tag="商品订单购物车",
            parameters=[{"name": "keyword", "in": "query", "type": "string"}],
            response_examples={"total": 1},
            source="markdown",
        ),
        ApiIntermediateMeta(
            path="/api/v1/orders",
            method="POST",
            summary="创建订单",
            tag="商品订单购物车",
            request_body={"fields": [{"name": "sku_id", "type": "string"}]},
            response_examples={"order_id": "1"},
            source="curl",
        ),
        ApiIntermediateMeta(
            path="/users",
            method="GET",
            summary="查询用户列表",
            tag="用户管理",
            parameters=[{"name": "page", "in": "query", "type": "integer"}],
            response_examples=[{"id": "u_1"}],
            source="markdown",
        ),
    ]


def test_tag_and_summary_from_metadata():
    doc = OpenApiAssembler(_tagged_metas()).assemble()

    assert doc["paths"]["/api/v1/products"]["get"]["summary"] == "查询文件列表"
    assert doc["paths"]["/api/v1/products"]["get"]["tags"] == ["商品订单购物车"]
    assert doc["paths"]["/api/v1/orders"]["post"]["tags"] == ["商品订单购物车"]
    assert doc["paths"]["/users"]["get"]["tags"] == ["用户管理"]
    # 分组名不再取路径首段 "api" / "users"
    assert "api" not in [t["name"] for t in doc["tags"]]
    # 文档级 tags 按首次出现顺序声明，且只包含被使用的分组
    assert [t["name"] for t in doc["tags"]] == ["商品订单购物车", "用户管理"]
    # 路径保持原样
    assert sorted(doc["paths"]) == ["/api/v1/orders", "/api/v1/products", "/users"]
    OpenApiValidator(doc).validate()


def test_tag_falls_back_to_first_path_segment():
    metas = [
        ApiIntermediateMeta(path="/api/v1/products", method="GET", response_examples={"a": 1}),
        ApiIntermediateMeta(path="/users", method="GET", response_examples={"a": 1}),
    ]
    doc = OpenApiAssembler(metas).assemble()
    assert doc["paths"]["/api/v1/products"]["get"]["tags"] == ["api"]
    assert doc["paths"]["/users"]["get"]["tags"] == ["users"]


def test_summary_falls_back_to_method_and_path():
    metas = [
        ApiIntermediateMeta(path="/api/v1/products", method="GET", response_examples={"a": 1})
    ]
    doc = OpenApiAssembler(metas).assemble()
    assert doc["paths"]["/api/v1/products"]["get"]["summary"] == "GET /api/v1/products"


def test_base_spec_tags_are_inherited_and_preserved():
    base = {
        "openapi": "3.0.3",
        "info": {"title": "Base", "version": "1.0.0"},
        "tags": [{"name": "商品订单购物车", "description": "商品、订单与购物车相关接口"}],
        "paths": {
            "/legacy": {
                "get": {"tags": ["商品订单购物车"], "responses": {"200": {"description": "OK"}}}
            }
        },
    }
    doc = OpenApiAssembler(_tagged_metas(), base_spec=base).assemble()
    names = [t["name"] for t in doc["tags"]]
    assert names[:2] == ["商品订单购物车", "用户管理"]
    # 基准契约里对该分组的说明被继承，而不是被覆盖成裸 name
    assert doc["tags"][0]["description"] == "商品、订单与购物车相关接口"


def test_risk_report_flags_missing_summary_and_tag():
    metas = [
        ApiIntermediateMeta(
            path="/api/v1/products",
            method="GET",
            parameters=[{"name": "page", "in": "query"}],
            response_examples={"a": 1},
        )
    ]
    report = RiskReportBuilder(metas).build()
    issues = [i.get("issue") for i in report["missing_info"]]
    assert "缺少接口功能名称（summary）" in issues
    assert any(i.get("scope") == "global" and "业务分组" in i["issue"] for i in report["missing_info"])


def test_recursive_split():
    text = "\n\n".join(f"段落{i} " + "x" * 200 for i in range(20))
    chunks = recursive_split(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert recursive_split("") == []
