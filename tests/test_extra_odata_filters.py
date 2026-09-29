from __future__ import annotations

from agentebc_worker.job_spec import parse_extra_odata_filter_lines


def test_string_field_uses_text_not_boolean() -> None:
    parsed = parse_extra_odata_filter_lines(
        "Esperar_Orden_Cliente | No",
        field_types={"Esperar_Orden_Cliente": "string"},
    )
    assert parsed["Esperar_Orden_Cliente"] == "No"


def test_false_is_boolean_only_when_field_is_boolean() -> None:
    assert parse_extra_odata_filter_lines(
        "onHold | false",
        field_types={"onHold": "boolean"},
    )["onHold"] is False

    assert parse_extra_odata_filter_lines(
        "Esperar_Orden_Cliente | false",
        field_types={"Esperar_Orden_Cliente": "string"},
    )["Esperar_Orden_Cliente"] == "false"


def test_multiple_filter_lines() -> None:
    parsed = parse_extra_odata_filter_lines(
        "A | No\nB | Yes",
        field_types={"A": "string", "B": "string"},
    )
    assert parsed == {"A": "No", "B": "Yes"}
