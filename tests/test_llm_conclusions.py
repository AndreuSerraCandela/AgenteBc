from agentebc.diagnosis import DiagnosticService
from agentebc.documents import DocumentReference
from agentebc.evidence_enrichment import EvidenceItem
from agentebc.llm_conclusions import build_conclusion_prompt
from agentebc.models import Incident
from agentebc.web_preview import PreviewMessage


def _sample_document() -> DocumentReference:
    return DocumentReference(
        company="Piscis Dos Tres Hache, S.L.",
        kind="sales_invoice",
        number="P4941",
        document_type="Invoice",
        status="Open",
        system_id="00000000-0000-0000-0000-000000000001",
        posting_date="2024-11-01",
    )


def _sample_message() -> PreviewMessage:
    return PreviewMessage(
        message_type="Error",
        description=(
            "Fecha registro no está dentro del intervalo de fechas de "
            "registro permitidas."
        ),
        context="Sales Header: Factura,P4941",
        context_field="Fecha registro",
        source='General Ledger Setup: ""',
        source_field="Permitir registro desde",
        additional_information=None,
        call_stack=(
            '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22'
        ),
    )


def test_build_conclusion_prompt_includes_enrichments() -> None:
    diagnosis = DiagnosticService(None).diagnose(
        Incident(
            error_text=_sample_message().description,
            call_stack=_sample_message().call_stack,
        )
    )
    prompt = build_conclusion_prompt(
        case_label="Factura de venta / Vista previa de registro",
        document=_sample_document(),
        message=_sample_message(),
        diagnosis=diagnosis,
        enrichments=(
            EvidenceItem(
                kind="sql",
                title="Configuración contable (SQL)",
                rows=(
                    ("Permitir registro desde", "2024-12-30 00:00:00"),
                    ("Permitir registro hasta", "2025-12-01 00:00:00"),
                ),
            ),
        ),
    )

    assert "P4941" in prompt
    assert "2024-11-01" in prompt
    assert "Permitir registro desde: 2024-12-30 00:00:00" in prompt
    assert "Sales-Post" in prompt
    assert "Causa raíz probable" in prompt
