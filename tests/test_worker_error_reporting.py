from __future__ import annotations

from agentebc.web_preview import PreviewMessage, PreviewResult
from agentebc_worker.batch_report import build_skill_batch_report, format_report_plain_text
from agentebc_worker.error_reporting import error_detail_from_preview, format_error_detail_text
from agentebc_worker.runner import BatchRunResult, DocumentRunOutcome
from agentebc_worker.skills import SkillStore
from pathlib import Path


def test_format_error_detail_includes_stack_and_rows() -> None:
    result = PreviewResult(
        outcome="errors",
        title="Factura venta",
        messages=(
            PreviewMessage(
                message_type="Error",
                description="Dimensión obligatoria",
                context="Validación",
                context_field="Dimensión",
                source="Table37",
                source_field="Shortcut Dimension 1 Code",
                additional_information="Línea 10000",
                call_stack="Codeunit 80\nLine 12",
            ),
        ),
        raw_rows=("Col1|Col2", "Val1|Val2"),
        screenshot_path=Path("reports/x.png"),
    )
    detail = error_detail_from_preview(result)
    text = format_error_detail_text(detail)
    assert "Dimensión obligatoria" in text
    assert "Pila de llamadas" in text
    assert "Codeunit 80" in text
    assert "Col1|Col2" not in text
    assert "Resultado acción web" not in text
    assert "x.png" in text


def test_plain_text_report_sections_and_ai_per_invoice() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = SkillStore(
        root / "tests" / "_unused",
        bundled_dirs=(root / "config" / "skills",),
    ).get("malla_publicidad_facturar_ventas")
    result = BatchRunResult(
        preview_summary="Empresa: Malla Publicidad",
        dry_run=False,
        outcomes=(
            DocumentRunOutcome(
                number="FV-1",
                outcome="error",
                error="Dimensión obligatoria",
                fields={"contract": "C-99"},
                error_detail={
                    "messages": [
                        {
                            "message_type": "Error",
                            "description": "Dimensión obligatoria",
                            "context": None,
                            "context_field": None,
                            "source": None,
                            "source_field": None,
                            "additional_information": None,
                            "call_stack": None,
                        }
                    ]
                },
            ),
            DocumentRunOutcome(
                number="FV-2",
                outcome="success",
                fields={"contract": "C-100"},
            ),
        ),
    )
    report = build_skill_batch_report(skill, result)
    rows = [dict(row) for row in report.rows]
    rows[0]["ai_conclusion"] = "Revisar dimensión PRINCIPAL en la línea."
    from dataclasses import replace

    report = replace(report, rows=tuple(rows))
    text = format_report_plain_text(report)
    assert "FACTURAS REGISTRADAS CORRECTAMENTE" in text
    assert "FACTURAS NO REGISTRADAS" in text
    assert "CONCLUSIONES IA (SOLO FACTURAS CON ERROR" in text
    assert "Dimensión obligatoria" in text
    assert "Revisar dimensión PRINCIPAL" in text
    assert "Registro correcto." not in text
    assert "Detalle completo del error" not in text
    assert "Filas crudas" not in text
    assert "Mensajes de error (BC)" not in text
