from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

FORBIDDEN_SQL = re.compile(
    r"\b("
    r"alter|backup|create|delete|deny|drop|execute|exec|grant|insert|kill|"
    r"merge|reconfigure|restore|revoke|truncate|update|use|xp_cmdshell"
    r")\b",
    flags=re.IGNORECASE,
)


class UnsafeSqlError(ValueError):
    """La consulta no cumple la política local de solo lectura."""


class SqlReadOnlyClient:
    """Ejecuta SELECT con transacción revertida y sin método de escritura."""

    def __init__(self, connection_string: str) -> None:
        if not connection_string.strip():
            raise ValueError("La cadena de conexión SQL está vacía")
        self._connection_string = connection_string

    def query(
        self,
        statement: str,
        parameters: Sequence[Any] = (),
        *,
        max_rows: int = 200,
    ) -> list[dict[str, Any]]:
        _validate_read_only(statement)
        if max_rows < 1 or max_rows > 10_000:
            raise ValueError("max_rows debe estar entre 1 y 10000")

        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError(
                "El acceso SQL requiere instalar 'agente-bc[sql]'"
            ) from exc

        connection = pyodbc.connect(
            self._connection_string,
            autocommit=False,
            timeout=10,
        )
        try:
            cursor = connection.cursor()
            cursor.execute(statement, tuple(parameters))
            columns = [column[0] for column in cursor.description or ()]
            rows = cursor.fetchmany(max_rows)
            return [dict(zip(columns, row, strict=True)) for row in rows]
        finally:
            connection.rollback()
            connection.close()


def _validate_read_only(statement: str) -> None:
    normalized = _remove_comments(statement).strip()
    if not normalized:
        raise UnsafeSqlError("La consulta SQL está vacía")
    if ";" in normalized.rstrip(";"):
        raise UnsafeSqlError("Solo se permite una sentencia SQL")
    first_word = re.match(r"[a-z]+", normalized, flags=re.IGNORECASE)
    if not first_word or first_word.group(0).lower() not in {"select", "with"}:
        raise UnsafeSqlError("Solo se permiten consultas SELECT o WITH")
    forbidden = FORBIDDEN_SQL.search(normalized)
    if forbidden:
        raise UnsafeSqlError(
            f"La consulta contiene la operación no permitida: {forbidden.group(0)}"
        )


def _remove_comments(statement: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", " ", statement, flags=re.DOTALL)
    return re.sub(r"--[^\r\n]*", " ", without_blocks)
