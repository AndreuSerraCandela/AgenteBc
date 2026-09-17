from pathlib import Path

from agentebc.diagnosis import DiagnosticService
from agentebc.models import Incident


def test_report_marks_code_matches_as_candidates(tmp_path: Path) -> None:
    (tmp_path / "Posting.al").write_text(
        "trigger OnRun()\nbegin\n    Error('Falta configuración');\nend;",
        encoding="utf-8",
    )
    incident = Incident(
        error_text="Falta configuración",
        document_number="FV-1001",
    )

    report = DiagnosticService(tmp_path).diagnose(incident)

    assert report.confidence == "media"
    assert report.source_matches
    assert "no demuestra" in report.summary
    assert report.incident.document_number == "FV-1001"


def test_report_states_when_sources_are_not_configured() -> None:
    report = DiagnosticService(None).diagnose(Incident(error_text="Error de prueba"))

    assert report.confidence == "baja"
    assert any(
        "No se configuró un directorio" in limitation
        for limitation in report.limitations
    )
