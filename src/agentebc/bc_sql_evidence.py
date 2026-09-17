from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .sql_reader import SqlReadOnlyClient


@dataclass(frozen=True, slots=True)
class PostingWindow:
    allow_from: datetime | None
    allow_to: datetime | None


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    number: str
    name: str | None
    blocked: str | None


class BusinessCentralSqlEvidence:
    def __init__(self, client: SqlReadOnlyClient) -> None:
        self._client = client

    def posting_window(self, company: str) -> PostingWindow | None:
        location = self._find_company_table(company, "General Ledger Setup")
        if location is None:
            return None
        schema, table = location
        rows = self._client.query(
            f"SELECT [Allow Posting From] AS allow_from, "
            f"[Allow Posting To] AS allow_to FROM {schema}.{table}",
            max_rows=1,
        )
        if not rows:
            return None
        return PostingWindow(
            allow_from=rows[0].get("allow_from"),
            allow_to=rows[0].get("allow_to"),
        )

    def customer_record(
        self,
        company: str,
        customer_no: str,
    ) -> CustomerRecord | None:
        location = self._find_company_table(company, "Customer")
        if location is None:
            return None
        schema, table = location
        rows = self._client.query(
            f"SELECT [No_] AS number, [Name] AS name, [Blocked] AS blocked "
            f"FROM {schema}.{table} WHERE [No_] = ?",
            (customer_no,),
            max_rows=1,
        )
        if not rows:
            return None
        row = rows[0]
        return CustomerRecord(
            number=str(row.get("number") or customer_no),
            name=_optional_str(row.get("name")),
            blocked=_optional_str(row.get("blocked")),
        )

    def _find_company_table(
        self,
        company: str,
        table_name: str,
    ) -> tuple[str, str] | None:
        physical_company = company.replace(".", "_")
        pattern = (
            _escape_like(physical_company)
            + r"\$"
            + _escape_like(table_name)
            + r"\$%"
        )
        tables = self._client.query(
            "SELECT TABLE_SCHEMA, TABLE_NAME "
            "FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE ? ESCAPE '\\' "
            "AND TABLE_NAME NOT LIKE '%$ext' "
            "ORDER BY TABLE_NAME",
            (pattern,),
            max_rows=5,
        )
        if len(tables) != 1:
            return None
        schema = _identifier(str(tables[0]["TABLE_SCHEMA"]))
        table = _identifier(str(tables[0]["TABLE_NAME"]))
        return schema, table


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("[", "\\[")
    )


def _identifier(value: str) -> str:
    return "[" + value.replace("]", "]]") + "]"
