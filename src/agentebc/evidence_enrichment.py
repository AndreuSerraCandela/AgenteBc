from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .bc_sql_evidence import BusinessCentralSqlEvidence
from .sql_reader import SqlReadOnlyClient
from .web_preview import PreviewMessage


@dataclass(frozen=True, slots=True)
class BcSourceReference:
    table: str
    record_key: str | None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    kind: str
    title: str
    rows: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_bc_source_reference(source: str | None) -> BcSourceReference | None:
    if not source:
        return None
    if ":" not in source:
        return BcSourceReference(table=source.strip(), record_key=None)
    table, record_key = source.split(":", 1)
    table = table.strip()
    record_key = record_key.strip().strip('"').strip("'")
    if not table:
        return None
    return BcSourceReference(
        table=table,
        record_key=record_key or None,
    )


def source_table_matches(reference: BcSourceReference, *markers: str) -> bool:
    lowered = reference.table.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def enrich_from_message(
    message: PreviewMessage,
    company: str,
    sql_client: SqlReadOnlyClient | None,
) -> tuple[EvidenceItem, ...]:
    if sql_client is None:
        return ()
    reference = parse_bc_source_reference(message.source)
    if reference is None:
        return ()
    evidence = BusinessCentralSqlEvidence(sql_client)
    items: list[EvidenceItem] = []
    if source_table_matches(
        reference,
        "general ledger setup",
        "configuración contabilidad",
        "configuracion contabilidad",
    ):
        window = evidence.posting_window(company)
        if window is not None:
            items.append(
                EvidenceItem(
                    kind="sql",
                    title="Configuración contable (SQL)",
                    rows=(
                        (
                            "Permitir registro desde",
                            _format_optional_datetime(window.allow_from),
                        ),
                        (
                            "Permitir registro hasta",
                            _format_optional_datetime(window.allow_to),
                        ),
                    ),
                )
            )
    if source_table_matches(reference, "customer", "cliente") and reference.record_key:
        customer_no = reference.record_key
        if customer_no:
            customer = evidence.customer_record(company, customer_no)
            if customer is not None:
                items.append(
                    EvidenceItem(
                        kind="sql",
                        title=f"Cliente {customer.number} (SQL)",
                        rows=(
                            ("Número", customer.number),
                            ("Nombre", customer.name or "—"),
                            ("Bloqueado", customer.blocked or "—"),
                        ),
                    )
                )
    return tuple(items)


def format_enrichments_for_prompt(
    enrichments: tuple[EvidenceItem, ...],
) -> str:
    if not enrichments:
        return ""
    blocks: list[str] = []
    for item in enrichments:
        lines = [f"## {item.title}"] + [
            f"- {label}: {value}" for label, value in item.rows
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _format_optional_datetime(value: object | None) -> str:
    if value is None:
        return "Sin límite"
    return str(value)
