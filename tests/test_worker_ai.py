from __future__ import annotations

from dataclasses import replace

import pytest

from agentebc.config import Settings
from agentebc_worker.worker_ai import (
    build_worker_llm_client,
    resolve_worker_ai_provider,
    worker_ai_enabled,
)


def _settings(**overrides: object) -> Settings:
    base = Settings(
        odata_base_url="http://localhost:7048/BC/ODataV4",
        web_base_url=None,
        auth_mode="basic",
        username="u",
        password="p",
        company="C",
        license_token=None,
        license_url=None,
        license_client=None,
        source_path=None,
        alpackages_path=None,
        sql_connection_string=None,
        tls_verify=True,
        request_timeout_seconds=30.0,
        web_action_idle_timeout_seconds=60.0,
        web_action_max_attempts=3,
        browser_headless=False,
        browser_channel=None,
        ai_provider="deepseek_web",
        worker_ai_provider=None,
        lm_studio_url=None,
        lm_studio_model=None,
        worker_lm_studio_url=None,
        worker_lm_studio_model=None,
        deepseek_api_key=None,
        deepseek_model=None,
        deepseek_url=None,
        deepseek_web_url=None,
        deepseek_web_profile=None,
        deepseek_web_timeout_seconds=90.0,
        deepseek_web_login_timeout_seconds=120.0,
        deepseek_web_cdp_url=None,
        ai_web_cdp_url=None,
        google_ai_web_url=None,
        bc_agent_url=None,
        bc_agent_token=None,
        share_url=None,
        share_token=None,
        share_user=None,
        web_company_use_guid=False,
        web_use_windows_session=False,
        web_browser_profile=None,
    )
    return replace(base, **overrides)


def test_worker_defaults_to_lm_studio_when_worker_url_set() -> None:
    settings = _settings(worker_lm_studio_url="http://127.0.0.1:1234/v1")
    assert resolve_worker_ai_provider(settings) == "lm_studio"
    assert worker_ai_enabled(settings) is True
    client = build_worker_llm_client(settings)
    assert client.provider == "lm_studio"


def test_worker_explicit_provider_overrides() -> None:
    settings = _settings(
        worker_ai_provider="lm_studio",
        lm_studio_url="http://127.0.0.1:9999/v1",
    )
    client = build_worker_llm_client(settings)
    assert "127.0.0.1:9999" in client._chat_url


def test_worker_rejects_web_consultant_without_lm_studio() -> None:
    settings = _settings(ai_provider="deepseek_web")
    assert worker_ai_enabled(settings) is False
    with pytest.raises(ValueError, match="WORKER_AI_PROVIDER"):
        build_worker_llm_client(settings)
