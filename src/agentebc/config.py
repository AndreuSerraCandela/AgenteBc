from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .browser import normalize_browser_channel


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
    browser_channel: str | None
    ai_provider: str | None
    lm_studio_url: str | None
    lm_studio_model: str | None
    deepseek_api_key: str | None
    deepseek_model: str | None
    deepseek_url: str | None
    deepseek_web_url: str | None
    deepseek_web_profile: Path | None
    deepseek_web_timeout_seconds: float
    deepseek_web_login_timeout_seconds: float
    deepseek_web_cdp_url: str | None
    ai_web_cdp_url: str | None
    google_ai_web_url: str | None
    bc_agent_url: str | None
    bc_agent_token: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        cls._load_all_env_files(override=False)
        return cls._build_from_current_environment()

    @classmethod
    def load_fresh(cls, env_file: Path | None = None) -> "Settings":
        if env_file is not None:
            os.environ["AGENTEBC_ENV_FILE"] = str(env_file.expanduser())
        cls._load_all_env_files(override=True)
        return cls._build_from_current_environment()

    @classmethod
    def _load_all_env_files(cls, *, override: bool) -> None:
        env_file = Path(os.getenv("AGENTEBC_ENV_FILE", ".env")).expanduser()
        _load_env_file(env_file, override=override)
        bc_env_file = _optional("AGENTEBC_BC_ENV_FILE")
        if bc_env_file:
            _load_env_file(Path(bc_env_file).expanduser(), override=override)
        sql_env_file = _optional("AGENTEBC_SQL_ENV_FILE")
        if sql_env_file:
            _load_env_file(Path(sql_env_file).expanduser(), override=override)

    @classmethod
    def _build_from_current_environment(cls) -> "Settings":

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

        web_timeout_text = os.getenv("AGENTEBC_DEEPSEEK_WEB_TIMEOUT", "90")
        try:
            web_timeout = float(web_timeout_text)
        except ValueError as exc:
            raise ConfigurationError(
                "AGENTEBC_DEEPSEEK_WEB_TIMEOUT debe ser numérico"
            ) from exc
        if web_timeout <= 0:
            raise ConfigurationError(
                "AGENTEBC_DEEPSEEK_WEB_TIMEOUT debe ser positivo"
            )

        login_timeout_text = os.getenv("AGENTEBC_DEEPSEEK_WEB_LOGIN_TIMEOUT", "120")
        try:
            login_timeout = float(login_timeout_text)
        except ValueError as exc:
            raise ConfigurationError(
                "AGENTEBC_DEEPSEEK_WEB_LOGIN_TIMEOUT debe ser numérico"
            ) from exc
        if login_timeout <= 0:
            raise ConfigurationError(
                "AGENTEBC_DEEPSEEK_WEB_LOGIN_TIMEOUT debe ser positivo"
            )

        deepseek_web_profile = _optional("AGENTEBC_DEEPSEEK_WEB_PROFILE")

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
            browser_channel=_load_browser_channel(),
            ai_provider=_resolve_ai_provider(
                _optional("AGENTEBC_AI_PROVIDER"),
                lm_studio_url=_optional("AGENTEBC_LM_STUDIO_URL"),
                deepseek_api_key=_optional("AGENTEBC_DEEPSEEK_API_KEY"),
            ),
            lm_studio_url=_optional("AGENTEBC_LM_STUDIO_URL"),
            lm_studio_model=_optional("AGENTEBC_LM_STUDIO_MODEL"),
            deepseek_api_key=_optional("AGENTEBC_DEEPSEEK_API_KEY"),
            deepseek_model=_optional("AGENTEBC_DEEPSEEK_MODEL"),
            deepseek_url=_optional("AGENTEBC_DEEPSEEK_URL"),
            deepseek_web_url=_optional("AGENTEBC_DEEPSEEK_WEB_URL"),
            deepseek_web_profile=(
                Path(deepseek_web_profile).expanduser().resolve()
                if deepseek_web_profile
                else None
            ),
            deepseek_web_timeout_seconds=web_timeout,
            deepseek_web_login_timeout_seconds=login_timeout,
            deepseek_web_cdp_url=_optional("AGENTEBC_DEEPSEEK_WEB_CDP_URL"),
            ai_web_cdp_url=(
                _optional("AGENTEBC_AI_WEB_CDP_URL")
                or _optional("AGENTEBC_DEEPSEEK_WEB_CDP_URL")
            ),
            google_ai_web_url=_optional("AGENTEBC_GOOGLE_AI_WEB_URL"),
            bc_agent_url=_optional("AGENTEBC_BC_AGENT_URL"),
            bc_agent_token=_optional("AGENTEBC_BC_AGENT_TOKEN"),
        )
        settings.validate()
        return settings

    @property
    def ai_enabled(self) -> bool:
        if self.ai_provider == "lm_studio":
            return bool(self.lm_studio_url)
        if self.ai_provider == "deepseek":
            return bool(self.deepseek_api_key)
        if self.ai_provider in {"deepseek_web", "google_ai_web"}:
            return True
        return False

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
        if self.ai_provider == "lm_studio" and not self.lm_studio_url:
            raise ConfigurationError(
                "AGENTEBC_LM_STUDIO_URL es obligatorio si "
                "AGENTEBC_AI_PROVIDER=lm_studio"
            )
        if self.ai_provider == "deepseek" and not self.deepseek_api_key:
            raise ConfigurationError(
                "AGENTEBC_DEEPSEEK_API_KEY es obligatorio si "
                "AGENTEBC_AI_PROVIDER=deepseek"
            )
        if self.ai_provider and self.ai_provider not in {
            "lm_studio",
            "deepseek",
            "deepseek_web",
            "google_ai_web",
        }:
            raise ConfigurationError(
                "AGENTEBC_AI_PROVIDER debe ser lm_studio, deepseek, "
                "deepseek_web o google_ai_web"
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
            "browser_channel": self.browser_channel,
            "ai_provider": self.ai_provider,
            "ai_enabled": self.ai_enabled,
            "lm_studio_configured": bool(self.lm_studio_url),
            "lm_studio_model": self.lm_studio_model,
            "deepseek_configured": bool(self.deepseek_api_key),
            "deepseek_model": self.deepseek_model,
            "deepseek_url": self.deepseek_url,
            "deepseek_web_url": self.deepseek_web_url,
            "deepseek_web_profile": (
                str(self.deepseek_web_profile)
                if self.deepseek_web_profile
                else None
            ),
            "deepseek_web_timeout_seconds": self.deepseek_web_timeout_seconds,
            "deepseek_web_login_timeout_seconds": (
                self.deepseek_web_login_timeout_seconds
            ),
            "deepseek_web_cdp_configured": bool(self.deepseek_web_cdp_url),
            "ai_web_cdp_configured": bool(self.ai_web_cdp_url),
            "google_ai_web_url": self.google_ai_web_url,
            "bc_agent_configured": bool(self.bc_agent_url and self.bc_agent_token),
            "bc_agent_url": self.bc_agent_url,
        }


def _load_browser_channel() -> str | None:
    try:
        return normalize_browser_channel(_optional("AGENTEBC_BROWSER_CHANNEL"))
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def _resolve_ai_provider(
    explicit: str | None,
    *,
    lm_studio_url: str | None,
    deepseek_api_key: str | None,
) -> str | None:
    if explicit:
        return explicit.strip().lower()
    if lm_studio_url:
        return "lm_studio"
    if deepseek_api_key:
        return "deepseek"
    return None


def _optional(name: str, *, strip: bool = True) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip() if strip else value
    return value or None


def _load_env_file(path: Path, *, override: bool = False) -> None:
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
        if override:
            os.environ[name] = value
        else:
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
