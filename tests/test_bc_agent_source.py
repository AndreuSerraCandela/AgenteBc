import json
from unittest.mock import MagicMock, patch

from agentebc.bc_agent_source import BcAgentSourceClient


def test_search_call_stack_parses_matches() -> None:
    payload = {
        "ok": True,
        "matches": [
            {
                "path": "src/InvoicePosting.Codeunit.al",
                "line": 5,
                "excerpt": "5: Error('demo')",
                "score": 4.0,
            }
        ],
    }
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response

    client = BcAgentSourceClient("http://agent:5051", "secret")
    with patch("urllib.request.urlopen", return_value=response):
        matches = client.search_call_stack('"X"(Codeunit 1).P line 1')

    assert len(matches) == 1
    assert matches[0].path == "src/InvoicePosting.Codeunit.al"
    assert matches[0].line == 5
