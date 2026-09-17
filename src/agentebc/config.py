from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Configuración ausente o insegura."""


def _boolean(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ConfigurationError(f"{name} debe ser true o false")


@dataclass(frozen=True, slots=True)
class Settings:
    odata_base_url: str | None
    auth_mode: str
    username: str | None
    password: str | None
    company: str | None
    license_token: str | None
    license_url: str | None
    license_client: str | None
    source_path: Path | None
    alpackages_path: Path | None
    sql_connection_string: str | None
    tls_verify: bool
    request_timeout_seconds: float
    browser_headless: bool
    lm_studio_url: str | None
    lm_studio_model: str | None
    bc_agent_url: str | None
    bc_agent_token: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        env_file = Path(os.getenv("AGENTEBC_ENV_FILE", ".env")).expanduser()
        _load_env_file(env_file)
        bc_env_file = _optional("AGENTEBC_BC_ENV_FILE")
        if bc_env_file:
            _load_env_file(Path(bc_env_file).expanduser())
        sql_env_file = _optional("AGENTEBC_SQL_ENV_FILE")
        if sql_env_file:
            _load_env_file(Path(sql_env_file).expanduser())

        source = os.getenv("AGENTEBC_SOURCE_PATH")
        alpackages = os.getenv("AGENTEBC_ALPACKAGES_PATH")
        timeout_text = os.getenv("AGENTEBC_REQUEST_TIMEOUT", "30")
        try:
            timeout = float(timeout_text)
        except ValueError as exc:
            raise ConfigurationError(
                "AGENTEBC_REQUEST_TIMEOUT debe ser numérico"
            ) from exc
        if timeout <= 0:
            raise ConfigurationError("AGENTEBC_REQUEST_TIMEOUT debe ser positivo")

        settings = cls(
            odata_base_url=_optional("AGENTEBC_ODATA_BASE_URL"),
            auth_mode=os.getenv("AGENTEBC_AUTH_MODE", "windows").strip().lower(),
            username=(
                _optional("AGENTEBC_USERNAME") or _optional("BC_USERNAME")
            ),
            password=(
                _optional("AGENTEBC_PASSWORD") or _optional("BC_PASSWORD")
            ),
            company=_optional("AGENTEBC_COMPANY") or _optional("BC_COMPANY"),
            license_token=_optional("AGENTEBC_LICENSE_TOKEN"),
            license_url=_optional("AGENTEBC_LICENSE_URL"),
            license_client=_optional("AGENTEBC_LICENSE_CLIENT") or "Malla",
            source_path=Path(source).expanduser().resolve() if source else None,
            alpackages_path=(
                Path(alpackages).expanduser().resolve() if alpackages else None
            ),
            sql_connection_string=(
                _optional("AGENTEBC_SQL_CONNECTION_STRING", strip=False)
                or _legacy_sql_connection_string()
            ),
            tls_verify=_boolean(
                os.getenv("AGENTEBC_TLS_VERIFY", "true"),
                name="AGENTEBC_TLS_VERIFY",
            ),
            request_timeout_seconds=timeout,
            browser_headless=_boolean(
                os.getenv("AGENTEBC_BROWSER_HEADLESS", "false"),
                name="AGENTEBC_BROWSER_HEADLESS",
            ),
            lm_studio_url=_optional("AGENTEBC_LM_STUDIO_URL"),
            lm_studio_model=_optional("AGENTEBC_LM_STUDIO_MODEL"),
            bc_agent_url=_optional("AGENTEBC_BC_AGENT_URL"),
            bc_agent_token=_optional("AGENTEBC_BC_AGENT_TOKEN"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.auth_mode not in {"windows", "basic"}:
            raise ConfigurationError(
                "AGENTEBC_AUTH_MODE debe ser windows o basic"
            )
        if self.odata_base_url:
            parsed = urlparse(self.odata_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ConfigurationError("AGENTEBC_ODATA_BASE_URL no es una URL válida")
            if parsed.scheme != "https":
                raise ConfigurationError(
                    "Business Central debe consultarse mediante HTTPS"
                )
        if self.source_path and not self.source_path.is_dir():
            raise ConfigurationError(
                f"AGENTEBC_SOURCE_PATH no es un directorio: {self.source_path}"
            )
        if self.alpackages_path and not self.alpackages_path.is_dir():
            raise ConfigurationError(
                "AGENTEBC_ALPACKAGES_PATH no es un directorio: "
                f"{self.alpackages_path}"
            )
        if self.bc_agent_url and not self.bc_agent_token:
            raise ConfigurationError(
                "AGENTEBC_BC_AGENT_TOKEN es obligatorio si se configura "
                "AGENTEBC_BC_AGENT_URL"
            )

    def safe_summary(self) -> dict[str, object]:
        return {
            "odata_base_url": self.odata_base_url,
            "auth_mode": self.auth_mode,
            "username_configured": bool(self.username),
            "password_configured": bool(self.password),
            "bc_credentials_ready": (
                self.auth_mode == "windows"
                or bool(self.username and self.password)
            ),
            "company": self.company,
            "license_token_configured": bool(self.license_token),
            "license_url": self.license_url,
            "license_client": self.license_client,
            "source_path": str(self.source_path) if self.source_path else None,
            "alpackages_path": (
                str(self.alpackages_path) if self.alpackages_path else None
            ),
            "sql_configured": bool(self.sql_connection_string),
            "tls_verify": self.tls_verify,
            "request_timeout_seconds": self.request_timeout_seconds,
            "browser_headless": self.browser_headless,
            "lm_studio_configured": bool(self.lm_studio_url),
            "lm_studio_model": self.lm_studio_model,
            "bc_agent_configured": bool(self.bc_agent_url and self.bc_agent_token),
            "bc_agent_url": self.bc_agent_url,
        }


def _optional(name: str, *, strip: bool = True) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip() if strip else value
    return value or None


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"No se pudo leer el fichero de entorno: {path}") from exc

    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigurationError(
                f"Línea {number} no válida en el fichero de entorno: {path}"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ConfigurationError(
                f"Variable no válida en la línea {number}: {path}"
            )
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _legacy_sql_connection_string() -> str | None:
    values = {
        "server": _optional("SQL_SERVER"),
        "database": _optional("SQL_DATABASE"),
        "user": _optional("SQL_USER"),
        "password": _optional("SQL_PASSWORD"),
    }
    configured = [name for name, value in values.items() if value]
    if not configured:
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        return None
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={_odbc_value(values['server'])};"
        f"DATABASE={_odbc_value(values['database'])};"
        f"UID={_odbc_value(values['user'])};"
        f"PWD={_odbc_value(values['password'])};"
        "Encrypt=yes;TrustServerCertificate=yes;ApplicationIntent=ReadOnly"
    )


def _odbc_value(value: str | None) -> str:
    assert value is not None
    return "{" + value.replace("}", "}}") + "}"
