from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from .bc_client import BusinessCentralReadClient
from .document_types import DocumentTypeDefinition


@dataclass(frozen=True, slots=True)
class DocumentReference:
    company: str
    kind: str
    number: str
    document_type: str
    status: str
    system_id: str
    posting_date: str | None


class DocumentNotFoundError(LookupError):
    pass


class DocumentReader:
    SERVICES = {
        "sales": "salesDocuments",
        "purchase": "purchaseDocuments",
    }

    def __init__(self, client: BusinessCentralReadClient) -> None:
        self._client = client

    def list_companies(self) -> list[str]:
        data = self._client.get("Company")
        rows = data.get("value", []) if isinstance(data, dict) else data
        names = {
            str(row.get("Name") or row.get("name") or "").strip()
            for row in rows
            if isinstance(row, dict)
        }
        return sorted(name for name in names if name)

    def find_invoice(
        self,
        *,
        company: str,
        kind: str,
        number: str,
    ) -> DocumentReference:
        service = self.SERVICES.get(kind)
        if service is None:
            raise ValueError("El tipo debe ser sales o purchase")
        definition = DocumentTypeDefinition.from_dict(
            {
                "id": kind,
                "label": "Factura de venta" if kind == "sales" else "Factura de compra",
                "page_id": 43 if kind == "sales" else 51,
                "source_table": "Sales Header" if kind == "sales" else "Purchase Header",
                "odata_service": service,
                "odata_key_field": "number",
                "odata_select_fields": {
                    "system_id": "id",
                    "number": "number",
                    "document_type": "documentType",
                    "status": "status",
                    "posting_date": "postingDate",
                },
                "odata_filters": {"documentType": "Invoice"},
            }
        )
        return self.find_document(
            company=company,
            definition=definition,
            number=number,
        )

    def find_document(
        self,
        *,
        company: str,
        definition: DocumentTypeDefinition,
        number: str,
    ) -> DocumentReference:
        number = number.strip()
        if not company.strip() or not number:
            raise ValueError("La empresa y el número son obligatorios")

        filters = [
            f"{definition.odata_key_field} eq {_odata_literal(number)}"
        ]
        filters.extend(
            f"{field} eq {_odata_literal(value)}"
            for field, value in definition.odata_filters.items()
        )
        selected_fields = set(definition.odata_select_fields.values())
        selected_fields.add(definition.odata_key_field)
        query = urlencode(
            {
                "company": company,
                "$filter": " and ".join(filters),
                "$select": ",".join(sorted(selected_fields)),
            }
        )
        data = self._client.get(f"{definition.odata_service}?{query}")
        rows = data.get("value", []) if isinstance(data, dict) else data
        if not rows:
            raise DocumentNotFoundError(
                f"No existe {definition.label} {number} en {company}"
            )
        row = rows[0]
        fields = definition.odata_select_fields

        def value(name: str, default: str = "") -> str:
            field_name = fields.get(name)
            raw = row.get(field_name) if field_name else None
            return str(raw) if raw is not None else default

        return DocumentReference(
            company=company,
            kind=definition.id,
            number=value("number", str(row.get(definition.odata_key_field, number))),
            document_type=value("document_type"),
            status=value("status"),
            system_id=value("system_id"),
            posting_date=value("posting_date") or None,
        )


def _odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
