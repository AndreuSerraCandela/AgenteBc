from __future__ import annotations

from agentebc_worker.list_documents import _row_still_open_for_posting


def test_open_without_posting_no_is_pending() -> None:
    assert _row_still_open_for_posting({"Status": "Open", "Posting_No": ""})


def test_released_is_pending() -> None:
    assert _row_still_open_for_posting(
        {"Status": "Released", "Posting_No": ""},
    )


def test_posting_no_set_is_not_pending() -> None:
    assert not _row_still_open_for_posting(
        {"Status": "Open", "Posting_No": "ML257397"},
    )
