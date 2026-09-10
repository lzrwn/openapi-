from app.agent.models import ApiIntermediateMeta
from app.openapi_build.assembler import OpenApiAssembler
from app.openapi_build.diff import DiffHelper
from app.openapi_build.validator import OpenApiValidator
from app.preprocessing.splitter import recursive_split
from app.reporting.risk_report import RiskReportBuilder


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


def test_recursive_split():
    text = "\n\n".join(f"段落{i} " + "x" * 200 for i in range(20))
    chunks = recursive_split(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert recursive_split("") == []
