from datetime import UTC, datetime

from agentebc.models import DiagnosticReport, Evidence, Incident, ProposedSolution
from agentebc.webapp import _diagnosis_from_dict, _parse_observed_at, _serialize_diagnosis


def test_parse_observed_at_accepts_iso_and_http_dates() -> None:
    iso = datetime(2026, 9, 16, 8, 33, 44, tzinfo=UTC)
    assert _parse_observed_at(iso.isoformat()) == iso
    assert _parse_observed_at("Wed, 16 Sep 2026 08:33:44 GMT") == iso


def test_serialize_diagnosis_uses_iso_observed_at() -> None:
    observed_at = datetime(2026, 9, 16, 8, 33, 44, tzinfo=UTC)
    diagnosis = DiagnosticReport(
        incident=Incident(
            error_text="Cliente bloqueado",
            observed_at=observed_at,
        ),
        summary="Resumen",
        confidence="alta",
        evidence=(),
        source_matches=(),
        proposed_solutions=(),
        limitations=(),
    )
    serialized = _serialize_diagnosis(diagnosis)
    assert serialized["incident"]["observed_at"] == observed_at.isoformat()


def test_diagnosis_from_dict_round_trip_with_http_date() -> None:
    observed_at = datetime(2026, 9, 16, 8, 33, 44, tzinfo=UTC)
    diagnosis = DiagnosticReport(
        incident=Incident(
            error_text="Cliente bloqueado",
            observed_at=observed_at,
        ),
        summary="Resumen",
        confidence="alta",
        evidence=(Evidence(kind="sql", description="Cliente", value={"blocked": True}),),
        source_matches=(),
        proposed_solutions=(
            ProposedSolution(
                description="Desbloquear cliente",
                verification="Reintentar registro",
            ),
        ),
        limitations=(),
    )
    payload = _serialize_diagnosis(diagnosis)
    payload["incident"]["observed_at"] = "Wed, 16 Sep 2026 08:33:44 GMT"
    restored = _diagnosis_from_dict(payload)
    assert restored.incident.error_text == "Cliente bloqueado"
    assert restored.incident.observed_at == observed_at
