from __future__ import annotations

from dataclasses import dataclass

from .bc_client import BusinessCentralReadClient, BusinessCentralReadError
from .bc_sql_evidence import CustomerRecord, PostingWindow
from .documents import bc_urlencode, _odata_literal


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    number: str
    global_dimension_1: str | None
    global_dimension_2: str | None


class BusinessCentralODataEvidence:
    def __init__(self, client: BusinessCentralReadClient) -> None:
        self._client = client

    def posting_window(self, company: str) -> PostingWindow | None:
        for service in ("generalLedgerSetups", "generalLedgerSetup"):
            try:
                query = bc_urlencode(
                    {
                        "company": company,
                        "$select": "allowPostingFrom,allowPostingTo",
                        "$top": "1",
                    }
                )
                data = self._client.get(f"{service}?{query}")
                rows = data.get("value", []) if isinstance(data, dict) else data
                if not rows or not isinstance(rows[0], dict):
                    continue
                row = rows[0]
                return PostingWindow(
                    allow_from=row.get("allowPostingFrom"),
                    allow_to=row.get("allowPostingTo"),
                )
            except BusinessCentralReadError:
                continue
        return None

    def customer_record(
        self,
        company: str,
        customer_no: str,
    ) -> CustomerRecord | None:
        for service in ("customers", "Customer"):
            try:
                query = bc_urlencode(
                    {
                        "company": company,
                        "$filter": f"number eq {_odata_literal(customer_no)}",
                        "$select": "number,displayName,name,blocked",
                        "$top": "1",
                    }
                )
                data = self._client.get(f"{service}?{query}")
                rows = data.get("value", []) if isinstance(data, dict) else data
                if not rows or not isinstance(rows[0], dict):
                    continue
                row = rows[0]
                name = _optional_str(row.get("displayName")) or _optional_str(
                    row.get("name")
                )
                return CustomerRecord(
                    number=str(row.get("number") or customer_no),
                    name=name,
                    blocked=_optional_str(row.get("blocked")),
                )
            except BusinessCentralReadError:
                continue
        return None

    def resource_record(
        self,
        company: str,
        resource_no: str,
    ) -> ResourceRecord | None:
        for service in ("resources", "Resource"):
            try:
                query = bc_urlencode(
                    {
                        "company": company,
                        "$filter": f"number eq {_odata_literal(resource_no)}",
                        "$select": (
                            "number,globalDimension1Code,globalDimension2Code,"
                            "shortcutDimension1Code,shortcutDimension2Code"
                        ),
                        "$top": "1",
                    }
                )
                data = self._client.get(f"{service}?{query}")
                rows = data.get("value", []) if isinstance(data, dict) else data
                if not rows or not isinstance(rows[0], dict):
                    continue
                row = rows[0]
                dim1 = _optional_str(row.get("globalDimension1Code")) or _optional_str(
                    row.get("shortcutDimension1Code")
                )
                dim2 = _optional_str(row.get("globalDimension2Code")) or _optional_str(
                    row.get("shortcutDimension2Code")
                )
                return ResourceRecord(
                    number=str(row.get("number") or resource_no),
                    global_dimension_1=dim1,
                    global_dimension_2=dim2,
                )
            except BusinessCentralReadError:
                continue
        return None


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
