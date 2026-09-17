from agentebc.evidence_enrichment import (
    BcSourceReference,
    EvidenceItem,
    enrich_from_message,
    format_enrichments_for_prompt,
    parse_bc_source_reference,
    source_table_matches,
)
from agentebc.web_preview import PreviewMessage


class FakeSqlClient:
    def __init__(self, table_name: str, rows: list[dict]) -> None:
        self.table_name = table_name
        self.rows = rows
        self.calls = 0

    def query(self, statement, parameters=(), *, max_rows=200):
        self.calls += 1
        if "INFORMATION_SCHEMA.TABLES" in statement:
            return [
                {
                    "TABLE_SCHEMA": "dbo",
                    "TABLE_NAME": f"EMPRESA_${self.table_name}$app",
                }
            ]
        return self.rows


def test_parse_bc_source_reference() -> None:
    assert parse_bc_source_reference('General Ledger Setup: ""') == BcSourceReference(
        "General Ledger Setup",
        None,
    )
    ref = parse_bc_source_reference('Customer: "43P000005"')
    assert ref is not None
    assert ref.table == "Customer"
    assert ref.record_key == "43P000005"


def test_enrich_general_ledger_setup_from_source_not_description() -> None:
    message = PreviewMessage(
        message_type="Error",
        description="Cualquier otro texto que no mencione fechas",
        context="Sales Header: Factura,P4941",
        context_field="Fecha registro",
        source='General Ledger Setup: ""',
        source_field="Permitir registro desde",
        additional_information=None,
        call_stack=None,
    )
    client = FakeSqlClient(
        "General Ledger Setup",
        [{"allow_from": "2024-12-30", "allow_to": "2025-12-01"}],
    )

    items = enrich_from_message(message, "EMPRESA", client)

    assert len(items) == 1
    assert items[0].title == "Configuración contable (SQL)"
    assert items[0].rows[0][1] == "2024-12-30"


def test_enrich_customer_from_normalized_source() -> None:
    message = PreviewMessage(
        message_type="Error",
        description=(
            "No puede registrar este tipo de documento cuando el cliente "
            "43P000031 está bloqueado por el tipo Factura"
        ),
        context="Sales Header: Factura,PI240014",
        context_field=None,
        source="Customer: 43P000031",
        source_field=None,
        additional_information="Comprobar campos del documento de ventas.",
        call_stack="Customer(Table 18).CustBlockedErrorMessage line 14",
    )
    client = FakeSqlClient(
        "Customer",
        [
            {
                "number": "43P000031",
                "name": "CLIENTE BLOQUEADO",
                "blocked": "Invoice",
            }
        ],
    )

    items = enrich_from_message(message, "EMPRESA", client)

    assert len(items) == 1
    assert items[0].title == "Cliente 43P000031 (SQL)"
    assert ("Bloqueado", "Invoice") in items[0].rows


def test_no_enrichment_without_source() -> None:
    message = PreviewMessage(
        message_type="Error",
        description="Error genérico",
        context="Validación de campo",
        context_field="Estado",
        source=None,
        source_field="Comentario Cabecera",
        additional_information=None,
        call_stack=None,
    )

    assert enrich_from_message(message, "EMPRESA", FakeSqlClient("Customer", [])) == ()


def test_format_enrichments_for_prompt() -> None:
    text = format_enrichments_for_prompt(
        (
            EvidenceItem(
                kind="sql",
                title="Cliente 43P000005 (SQL)",
                rows=(("Bloqueado", "Invoice"),),
            ),
        )
    )

    assert "## Cliente 43P000005 (SQL)" in text
    assert "- Bloqueado: Invoice" in text


def test_source_table_matches_spanish_and_english() -> None:
    ref = BcSourceReference("General Ledger Setup", None)
    assert source_table_matches(ref, "general ledger setup")
    ref_es = BcSourceReference("Configuración contabilidad", None)
    assert source_table_matches(ref_es, "configuración contabilidad")
