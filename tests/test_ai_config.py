import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_agentebc_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(tmp_path / ".env"))
    for name in list(os.environ):
        if name.startswith("AGENTEBC_") and name != "AGENTEBC_ENV_FILE":
            monkeypatch.delenv(name, raising=False)

from agentebc.config import ConfigurationError, Settings
from agentebc.deepseek_web import DeepSeekWebClient
from agentebc.google_ai_web import GoogleAiWebClient
from agentebc.llm_conclusions import (
    ChatCompletionClient,
    build_llm_client,
    request_ai_conclusion,
)
from agentebc.diagnosis import DiagnosticService
from agentebc.documents import DocumentReference
from agentebc.models import Incident
from agentebc.web_preview import PreviewMessage


def test_ai_provider_defaults_to_lm_studio_when_url_present(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_LM_STUDIO_URL=http://127.0.0.1:1234/v1",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_LM_STUDIO_URL",
        "AGENTEBC_DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()

    assert settings.ai_provider == "lm_studio"
    assert settings.ai_enabled is True


def test_deepseek_provider_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=deepseek",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigurationError, match="AGENTEBC_DEEPSEEK_API_KEY"):
        Settings.from_environment()


def test_build_deepseek_client_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=deepseek",
                "AGENTEBC_DEEPSEEK_API_KEY=sk-test",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_API_KEY",
        "AGENTEBC_DEEPSEEK_MODEL",
        "AGENTEBC_DEEPSEEK_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()
    client = build_llm_client(settings)

    assert isinstance(client, ChatCompletionClient)
    assert client.provider == "deepseek"
    assert client.model == "deepseek-chat"
    assert client._chat_url == "https://api.deepseek.com/v1/chat/completions"
    assert client._api_key == "sk-test"


def test_deepseek_web_provider_does_not_require_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=deepseek_web",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()

    assert settings.ai_provider == "deepseek_web"
    assert settings.ai_enabled is True


def test_build_deepseek_web_client(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "deepseek-profile"
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=deepseek_web",
                f"AGENTEBC_DEEPSEEK_WEB_PROFILE={profile}",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_WEB_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()
    client = build_llm_client(settings)

    assert isinstance(client, DeepSeekWebClient)
    assert client.provider == "deepseek_web"
    assert client._profile_dir == profile.resolve()
    assert client._cdp_url is None


def test_build_deepseek_web_client_with_cdp(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=deepseek_web",
                "AGENTEBC_DEEPSEEK_WEB_CDP_URL=http://127.0.0.1:9222",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_WEB_CDP_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()
    client = build_llm_client(settings)

    assert client._cdp_url == "http://127.0.0.1:9222"


class _FakeDeepSeekWebClient:
    model = "deepseek-web"
    provider = "deepseek_web"
    chat_url = "https://chat.deepseek.com"
    external_label = "DeepSeek"
    cdp_available = True

    def submit_prompt_only(self, user_prompt: str, system_prompt: str = "") -> None:
        self.last_prompt = user_prompt
        self.last_system_prompt = system_prompt


def test_deepseek_web_returns_external_view() -> None:
    client = _FakeDeepSeekWebClient()
    diagnosis = DiagnosticService(None).diagnose(
        Incident(error_text="Error de prueba")
    )
    result = request_ai_conclusion(
        client,
        case_label="Caso / Acción",
        document=DocumentReference(
            company="Empresa",
            kind="sales_invoice",
            number="P0001",
            document_type="Invoice",
            status="Open",
            system_id="00000000-0000-0000-0000-000000000001",
            posting_date=None,
        ),
        message=PreviewMessage(
            message_type="Error",
            description="Error de prueba",
            context=None,
            context_field=None,
            source=None,
            source_field=None,
            additional_information=None,
            call_stack=None,
        ),
        diagnosis=diagnosis,
    )

    assert result.external_view is True
    assert result.external_url == "https://chat.deepseek.com"
    assert result.external_cdp_available is True
    assert result.external_label == "DeepSeek"
    assert result.conclusion == ""
    assert result.error is None


def test_google_ai_web_provider_does_not_require_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=google_ai_web",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()

    assert settings.ai_provider == "google_ai_web"
    assert settings.ai_enabled is True


def test_build_google_ai_web_client(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AI_PROVIDER=google_ai_web",
                "AGENTEBC_AI_WEB_CDP_URL=http://127.0.0.1:9222",
                "AGENTEBC_GOOGLE_AI_WEB_URL=https://www.google.com/ai",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "AGENTEBC_ODATA_BASE_URL",
        "AGENTEBC_AI_PROVIDER",
        "AGENTEBC_AI_WEB_CDP_URL",
        "AGENTEBC_GOOGLE_AI_WEB_URL",
        "AGENTEBC_DEEPSEEK_WEB_CDP_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()
    client = build_llm_client(settings)

    assert isinstance(client, GoogleAiWebClient)
    assert client.provider == "google_ai_web"
    assert client._base_url == "https://www.google.com/ai"
    assert client._cdp_url == "http://127.0.0.1:9222"
    assert client.external_label == "Google Modo IA"


class _FakeGoogleAiWebClient:
    model = "google-ai-mode"
    provider = "google_ai_web"
    chat_url = "https://www.google.com/search?q=test&udm=50"
    external_label = "Google Modo IA"
    cdp_available = True

    def submit_prompt_only(self, user_prompt: str, system_prompt: str = "") -> None:
        self.last_prompt = user_prompt
        self.last_system_prompt = system_prompt


def test_google_ai_web_returns_external_view() -> None:
    client = _FakeGoogleAiWebClient()
    diagnosis = DiagnosticService(None).diagnose(
        Incident(error_text="Error de prueba")
    )
    result = request_ai_conclusion(
        client,
        case_label="Caso / Acción",
        document=DocumentReference(
            company="Empresa",
            kind="sales_invoice",
            number="P0001",
            document_type="Invoice",
            status="Open",
            system_id="00000000-0000-0000-0000-000000000001",
            posting_date=None,
        ),
        message=PreviewMessage(
            message_type="Error",
            description="Error de prueba",
            context=None,
            context_field=None,
            source=None,
            source_field=None,
            additional_information=None,
            call_stack=None,
        ),
        diagnosis=diagnosis,
    )

    assert result.external_view is True
    assert "google.com" in (result.external_url or "")
    assert result.external_cdp_available is True
    assert result.external_label == "Google Modo IA"
    assert result.conclusion == ""
    assert result.error is None
