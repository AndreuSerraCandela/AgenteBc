from pathlib import Path

from agentebc.config import Settings


def test_loads_project_and_referenced_sql_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sql_env = tmp_path / "db.local.env"
    sql_env.write_text(
        "\n".join(
            [
                "SQL_SERVER=db.local",
                "SQL_DATABASE=BC",
                "SQL_USER=reader",
                "SQL_PASSWORD=secret",
                "BC_COMPANY=Test Company",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AUTH_MODE=basic",
                f"AGENTEBC_SQL_ENV_FILE={sql_env}",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AUTH_MODE",
        "AGENTEBC_SQL_ENV_FILE",
        "AGENTEBC_COMPANY",
        "AGENTEBC_USERNAME",
        "AGENTEBC_PASSWORD",
        "SQL_SERVER",
        "SQL_DATABASE",
        "SQL_USER",
        "SQL_PASSWORD",
        "BC_COMPANY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(tmp_path / ".env"))

    settings = Settings.from_environment()

    assert settings.company == "Test Company"
    assert settings.sql_connection_string is not None
    assert "ApplicationIntent=ReadOnly" in settings.sql_connection_string
    assert settings.safe_summary()["sql_configured"] is True
    assert "secret" not in str(settings.safe_summary())
