from pathlib import Path

from agentebc.config import Settings
from agentebc.evidence_enrichment import (
    BcSourceReference,
    EvidenceItem,
    enrich_diagnostic_evidence,
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


def test_enrich_resource_from_error_description_sql() -> None:
    message = PreviewMessage(
        message_type="Error",
        description=(
            "Dimensión PROGRAMA en blanco en el recurso nº MP200000130021"
        ),
        context=None,
        context_field=None,
        source=None,
        source_field=None,
        additional_information=None,
        call_stack=None,
    )
    client = FakeSqlClient(
        "Resource",
        [{"number": "MP200000130021", "dim1": "EXTERIOR", "dim2": None}],
    )

    items = enrich_from_message(message, "GREPSA", client)

    assert len(items) == 1
    assert "MP200000130021" in items[0].title
    assert ("Global dimension 2", "(vacío)") in items[0].rows


def test_resolve_evidence_backend_auto_prefers_sql(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc/ODataV4",
                "AGENTEBC_AUTH_MODE=windows",
                "AGENTEBC_SQL_CONNECTION_STRING=DRIVER={x};SERVER=db;",
                "AGENTEBC_EVIDENCE_BACKEND=auto",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(tmp_path / ".env"))
    settings = Settings.from_environment()
    assert settings.resolve_evidence_backend() == "sql"


def test_enrich_diagnostic_evidence_odata_mode_without_sql(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeODataEvidence:
        def customer_record(self, company: str, customer_no: str):
            from agentebc.bc_sql_evidence import CustomerRecord

            return CustomerRecord(customer_no, "ACME", "")

    message = PreviewMessage(
        message_type="Error",
        description="Cliente bloqueado",
        context=None,
        context_field=None,
        source="Customer: 43P000005",
        source_field=None,
        additional_information=None,
        call_stack=None,
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc/ODataV4",
                "AGENTEBC_AUTH_MODE=windows",
                "AGENTEBC_EVIDENCE_BACKEND=odata",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(tmp_path / ".env"))
    for name in (
        "AGENTEBC_SQL_CONNECTION_STRING",
        "AGENTEBC_SQL_ENV_FILE",
        "SQL_SERVER",
        "SQL_DATABASE",
        "SQL_USER",
        "SQL_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.load_fresh(tmp_path / ".env")
    assert settings.resolve_evidence_backend() == "odata"

    import agentebc.evidence_enrichment as module

    original = module.BusinessCentralODataEvidence
    module.BusinessCentralODataEvidence = lambda _client: FakeODataEvidence()
    try:
        items = enrich_diagnostic_evidence(
            message,
            company="EMPRESA",
            settings=settings,
        )
    finally:
        module.BusinessCentralODataEvidence = original

    assert len(items) == 1
    assert items[0].title == "Cliente 43P000005 (OData)"
