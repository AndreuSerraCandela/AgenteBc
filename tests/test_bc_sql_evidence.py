from datetime import datetime

from agentebc.bc_sql_evidence import BusinessCentralSqlEvidence


class FakeSqlClient:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, statement, parameters=(), *, max_rows=200):
        self.calls += 1
        if self.calls == 1:
            assert "INFORMATION_SCHEMA.TABLES" in statement
            assert "PISCIS DOS TRES HACHE" in parameters[0]
            return [
                {
                    "TABLE_SCHEMA": "dbo",
                    "TABLE_NAME": (
                        "PISCIS DOS TRES HACHE, S_L_$General Ledger Setup$app"
                    ),
                }
            ]
        return [
            {
                "allow_from": datetime(2024, 12, 30),
                "allow_to": datetime(2025, 12, 1),
            }
        ]


def test_reads_company_posting_window() -> None:
    result = BusinessCentralSqlEvidence(FakeSqlClient()).posting_window(
        "PISCIS DOS TRES HACHE, S.L."
    )

    assert result is not None
    assert result.allow_from == datetime(2024, 12, 30)
    assert result.allow_to == datetime(2025, 12, 1)
