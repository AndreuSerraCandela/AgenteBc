from __future__ import annotations

from agentebc.bc_client import BusinessCentralReadClient, BusinessCentralReadError
from agentebc.document_types import DocumentTypeDefinition
from agentebc.documents import bc_urlencode


def infer_field_types(row: dict[str, object]) -> dict[str, str]:
    types: dict[str, str] = {}
    for key, value in row.items():
        if not isinstance(key, str) or key.startswith("@"):
            continue
        if isinstance(value, bool):
            types[key] = "boolean"
        elif isinstance(value, (int, float)):
            types[key] = "number"
        elif value is None:
            types[key] = "unknown"
        else:
            types[key] = "string"
    return types


def sample_field_values(row: dict[str, object]) -> dict[str, str]:
    samples: dict[str, str] = {}
    for key, value in row.items():
        if not isinstance(key, str) or key.startswith("@"):
            continue
        if value is None:
            samples[key] = ""
        elif isinstance(value, bool):
            samples[key] = "true" if value else "false"
        else:
            samples[key] = str(value)
    return samples


def fetch_odata_sample_row(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    company: str,
    *,
    odata_service: str | None = None,
) -> tuple[str, dict[str, object]]:
    company = company.strip()
    if not company:
        raise ValueError("Indique la empresa para listar campos OData")
    query = bc_urlencode(
        {
            "company": company,
            "$top": "1",
        }
    )
    service = (odata_service or "").strip() or definition.odata_service
    endpoint = f"{service}?{query}"
    try:
        data = client.get(endpoint)
    except BusinessCentralReadError as exc:
        raise ValueError(str(exc)) from exc
    rows = data.get("value", []) if isinstance(data, dict) else data
    if not rows or not isinstance(rows[0], dict):
        raise ValueError(
            f"No hay documentos de ejemplo en {service} "
            f"para listar campos (empresa {company!r})"
        )
    return service, rows[0]


def list_odata_field_names(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    company: str,
    *,
    odata_service: str | None = None,
) -> tuple[str, ...]:
    company = company.strip()
    if not company:
        raise ValueError("Indique la empresa para listar campos OData")
    _, row = fetch_odata_sample_row(
        client,
        definition,
        company,
        odata_service=odata_service,
    )
    names = sorted(
        key
        for key in row
        if isinstance(key, str) and not key.startswith("@")
    )
    return tuple(names)


def suggest_boolean_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    hints = (
        "esperar",
        "wait",
        "orden",
        "order",
        "cliente",
        "customer",
        "boolean",
        "hold",
    )
    return tuple(
        name
        for name in fields
        if any(fragment in name.casefold() for fragment in hints)
    )


def suggest_contract_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    hints = ("contract", "contrato", "quote", "order", "external", "reference")
    return tuple(
        name
        for name in fields
        if any(fragment in name.casefold() for fragment in hints)
    )


def suggest_key_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    exact = ("No", "no", "number", "Number", "Document_No", "documentNo")
    hits = [name for name in fields if name in exact]
    if hits:
        return tuple(dict.fromkeys(hits))
    hints = ("number", "document", "factura", "invoice", "no_")
    return tuple(
        name
        for name in fields
        if any(fragment in name.casefold() for fragment in hints)
    )


def suggest_report_label(odata_field: str) -> str:
    name = odata_field.replace("_x00BA__", "º").replace("_x00BA_", "º")
    name = name.replace("_", " ").strip()
    if not name:
        return odata_field
    return name[:1].upper() + name[1:]


def suggest_date_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    hints = ("posting", "document", "date", "fecha", "invoice")
    return tuple(
        name
        for name in fields
        if any(fragment in name.casefold() for fragment in hints)
    )
