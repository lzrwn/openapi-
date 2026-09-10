from app.agent.models import ApiIntermediateMeta
from app.core.errors import BusinessException
from app.openapi_build.assembler import OpenApiAssembler
from app.openapi_build.diff import DiffHelper
from app.openapi_build.validator import OpenApiValidator
from app.reporting.risk_report import RiskReportBuilder


class AgentWorkflow:
    def run(
        self,
        llm_client,
        preprocessor,
        extractor,
        base_spec: dict | None = None,
        title: str = "Generated API",
        version: str = "1.0.0",
    ) -> tuple[list[ApiIntermediateMeta], dict]:
        chunks = preprocessor.process()
        metas = extractor.extract(llm_client, chunks=chunks)

        doc = OpenApiAssembler(metas, base_spec=base_spec, title=title, version=version).assemble()

        risk_report = RiskReportBuilder(metas, llm_client=llm_client).build()
        try:
            OpenApiValidator(doc).validate()
        except BusinessException as e:
            risk_report.setdefault("validation_errors", []).append(
                {"code": int(e.code), "message": e.message, "detail": e.detail}
            )

        diff = DiffHelper(base_spec, doc).diff() if base_spec else None

        result = {"openapi": doc, "diff": diff, "risk_report": risk_report}
        return metas, result
