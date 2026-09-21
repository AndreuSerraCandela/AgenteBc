import os
from pathlib import Path

import pytest

from agentebc.config import ConfigurationError, Settings
from agentebc.env_store import (
    apply_env_updates,
    is_setup_complete,
    read_env_values,
    write_env_values,
)


def test_write_and_read_env_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env_values(
        env_file,
        {
            "AGENTEBC_ODATA_BASE_URL": "https://bc.local/BC/ODataV4",
            "AGENTEBC_COMPANY": "Empresa",
            "AGENTEBC_AUTH_MODE": "basic",
            "AGENTEBC_USERNAME": "user",
            "AGENTEBC_PASSWORD": "secret",
        },
    )
    values = read_env_values(env_file)
    assert values["AGENTEBC_COMPANY"] == "Empresa"
    assert values["AGENTEBC_PASSWORD"] == "secret"


def test_password_not_cleared_when_empty(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env_values(env_file, {"AGENTEBC_PASSWORD": "secret"})
    write_env_values(env_file, {"AGENTEBC_PASSWORD": ""})
    assert read_env_values(env_file)["AGENTEBC_PASSWORD"] == "secret"


def test_is_setup_complete_requires_company_and_odata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    write_env_values(
        env_file,
        {
            "AGENTEBC_ODATA_BASE_URL": "https://bc.local/BC/ODataV4",
            "AGENTEBC_AUTH_MODE": "basic",
            "AGENTEBC_USERNAME": "u",
            "AGENTEBC_PASSWORD": "p",
            "AGENTEBC_COMPANY": "Empresa",
        },
    )
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env_file))
    settings = apply_env_updates(env_file, {})
    assert is_setup_complete(settings) is True


def test_apply_env_updates_validates_settings(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env_file))
    for name in list(os.environ):
        if name.startswith("AGENTEBC_") and name != "AGENTEBC_ENV_FILE":
            monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        apply_env_updates(
            env_file,
            {
                "AGENTEBC_ODATA_BASE_URL": "http://inseguro.local/ODataV4",
                "AGENTEBC_COMPANY": "Empresa",
                "AGENTEBC_AUTH_MODE": "basic",
                "AGENTEBC_USERNAME": "u",
                "AGENTEBC_PASSWORD": "p",
            },
        )
