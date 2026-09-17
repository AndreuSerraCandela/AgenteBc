from unittest.mock import MagicMock

from agentebc.diagnosis import DiagnosticService
from agentebc.models import Incident, SourceMatch


def test_diagnosis_uses_remote_agent_when_local_has_no_matches() -> None:
    remote_client = MagicMock()
    remote_client.search_call_stack.return_value = (
        SourceMatch(
            path="Microsoft_Base Application_1.app!src/SalesPost.Codeunit.al",
            line=866,
            excerpt="866: ErrorMessageMgt.LogContextFieldError(",
            score=4.0,
        ),
    )
    service = DiagnosticService(
        None,
        bc_agent_client=remote_client,
    )
    report = service.diagnose(
        Incident(
            error_text="Fecha de registro no permitida",
            call_stack=(
                '"Sales-Post"(Codeunit 50016).CheckAndUpdatePostingDate line 2'
            ),
        )
    )
    assert len(report.source_matches) == 1
    assert ".app!" in report.source_matches[0].path
    remote_client.search_call_stack.assert_called_once()
