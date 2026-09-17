import pytest

from agentebc.sql_reader import UnsafeSqlError, _validate_read_only


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT TOP 10 * FROM [CRONUS$Sales Header]",
        "WITH invoices AS (SELECT * FROM [Sales]) SELECT * FROM invoices",
        "SELECT * FROM [Table] WHERE [No_] = ?;",
    ],
)
def test_accepts_read_queries(statement: str) -> None:
    _validate_read_only(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE [Sales] SET [Status] = 1",
        "DELETE FROM [Sales]",
        "SELECT * FROM [Sales]; DROP TABLE [Sales]",
        "EXEC dbo.RepairInvoice",
        "WITH changed AS (UPDATE [Sales] SET [Status] = 1 OUTPUT inserted.*) "
        "SELECT * FROM changed",
    ],
)
def test_rejects_write_or_multiple_statements(statement: str) -> None:
    with pytest.raises(UnsafeSqlError):
        _validate_read_only(statement)
