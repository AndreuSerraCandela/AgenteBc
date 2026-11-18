from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from .bc_client import BusinessCentralReadClient
from .bc_odata_evidence import BusinessCentralODataEvidence
from .bc_sql_evidence import BusinessCentralSqlEvidence
from .sql_reader import SqlReadOnlyClient
from .web_preview import PreviewMessage

if TYPE_CHECKING:
    from .config import Settings

_BLANK_DIMENSION_RESOURCE = re.compile(
    r"[Dd]imensi[oó]n\s+(?P<dimension>.+?)\s+en blanco en el recurso "
    r"n(?:[°º]|º)?\.?\s*(?P<resource>\S+)",
)


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


def enrich_diagnostic_evidence(
    message: PreviewMessage,
    *,
    company: str,
    settings: Settings,
) -> tuple[EvidenceItem, ...]:
    backend = settings.resolve_evidence_backend()
    if backend is None:
        return ()
    items: list[EvidenceItem] = []
    if backend == "sql":
        if settings.sql_connection_string:
            client = SqlReadOnlyClient(settings.sql_connection_string)
            items.extend(
                _enrich_from_source_reference(
                    message,
                    company,
                    sql=BusinessCentralSqlEvidence(client),
                    odata=None,
                    backend_label="SQL",
                )
            )
            items.extend(
                _enrich_resource_from_description(
                    message.description,
                    company,
                    sql=BusinessCentralSqlEvidence(client),
                    odata=None,
                    backend_label="SQL",
                )
            )
    elif backend == "odata" and settings.odata_base_url:
        odata = BusinessCentralODataEvidence(
            BusinessCentralReadClient(settings),
        )
        items.extend(
            _enrich_from_source_reference(
                message,
                company,
                sql=None,
                odata=odata,
                backend_label="OData",
            )
        )
        items.extend(
            _enrich_resource_from_description(
                message.description,
                company,
                sql=None,
                odata=odata,
                backend_label="OData",
            )
        )
    return tuple(items)


def enrich_from_message(
    message: PreviewMessage,
    company: str,
    sql_client: SqlReadOnlyClient | None,
) -> tuple[EvidenceItem, ...]:
    """Compatibilidad: enriquecimiento solo SQL (tests y llamadas antiguas)."""
    if sql_client is None:
        return ()
    sql = BusinessCentralSqlEvidence(sql_client)
    items = list(
        _enrich_from_source_reference(
            message,
            company,
            sql=sql,
            odata=None,
            backend_label="SQL",
        )
    )
    items.extend(
        _enrich_resource_from_description(
            message.description,
            company,
            sql=sql,
            odata=None,
            backend_label="SQL",
        )
    )
    return tuple(items)


def _enrich_from_source_reference(
    message: PreviewMessage,
    company: str,
    *,
    sql: BusinessCentralSqlEvidence | None,
    odata: BusinessCentralODataEvidence | None,
    backend_label: str,
) -> tuple[EvidenceItem, ...]:
    reference = parse_bc_source_reference(message.source)
    if reference is None:
        return ()
    items: list[EvidenceItem] = []
    if source_table_matches(
        reference,
        "general ledger setup",
        "configuración contabilidad",
        "configuracion contabilidad",
    ):
        window = None
        if sql is not None:
            window = sql.posting_window(company)
        elif odata is not None:
            window = odata.posting_window(company)
        if window is not None:
            items.append(
                EvidenceItem(
                    kind=backend_label.casefold(),
                    title=f"Configuración contable ({backend_label})",
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
            customer = None
            if sql is not None:
                customer = sql.customer_record(company, customer_no)
            elif odata is not None:
                customer = odata.customer_record(company, customer_no)
            if customer is not None:
                items.append(
                    EvidenceItem(
                        kind=backend_label.casefold(),
                        title=f"Cliente {customer.number} ({backend_label})",
                        rows=(
                            ("Número", customer.number),
                            ("Nombre", customer.name or "—"),
                            ("Bloqueado", customer.blocked or "—"),
                        ),
                    )
                )
    return tuple(items)


def _enrich_resource_from_description(
    description: str,
    company: str,
    *,
    sql: BusinessCentralSqlEvidence | None,
    odata: BusinessCentralODataEvidence | None,
    backend_label: str,
) -> tuple[EvidenceItem, ...]:
    match = _BLANK_DIMENSION_RESOURCE.search(description)
    if not match:
        return ()
    dimension = match.group("dimension").strip()
    resource_no = match.group("resource").strip().rstrip(".,;")
    record = None
    if sql is not None:
        record = sql.resource_record(company, resource_no)
    elif odata is not None:
        record = odata.resource_record(company, resource_no)
    if record is None:
        return ()
    return (
        EvidenceItem(
            kind=backend_label.casefold(),
            title=f"Recurso {record.number} ({backend_label})",
            rows=(
                ("Dimensión indicada en el error", dimension),
                (
                    "Global dimension 1",
                    record.global_dimension_1 or "(vacío)",
                ),
                (
                    "Global dimension 2",
                    record.global_dimension_2 or "(vacío)",
                ),
            ),
        ),
    )


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
