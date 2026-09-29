"""IA para informes del worker (LM Studio / API), independiente de la IA web del consultor."""
from __future__ import annotations

from agentebc.config import Settings
from agentebc.llm_conclusions import ChatCompletionClient

_WORKER_API_PROVIDERS = frozenset({"lm_studio", "deepseek"})


def resolve_worker_ai_provider(settings: Settings) -> str | None:
    explicit = (settings.worker_ai_provider or "").strip().lower()
    if explicit:
        return explicit
    if settings.worker_lm_studio_url or settings.lm_studio_url:
        return "lm_studio"
    if settings.ai_provider in _WORKER_API_PROVIDERS:
        return settings.ai_provider
    return None


def worker_ai_enabled(settings: Settings) -> bool:
    provider = resolve_worker_ai_provider(settings)
    if provider == "lm_studio":
        return bool(settings.worker_lm_studio_url or settings.lm_studio_url)
    if provider == "deepseek":
        return bool(settings.deepseek_api_key)
    return False


def build_worker_llm_client(settings: Settings) -> ChatCompletionClient:
    provider = resolve_worker_ai_provider(settings)
    if provider == "lm_studio":
        url = settings.worker_lm_studio_url or settings.lm_studio_url
        if not url:
            raise ValueError(
                "Informe worker: configure AGENTEBC_WORKER_LM_STUDIO_URL "
                "o AGENTEBC_LM_STUDIO_URL (LM Studio en marcha)."
            )
        model = (
            settings.worker_lm_studio_model
            or settings.lm_studio_model
            or "qwen2.5-32b-instruct"
        )
        return ChatCompletionClient(
            url,
            model=model,
            provider="lm_studio",
            timeout_seconds=settings.request_timeout_seconds,
        )
    if provider == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError(
                "Informe worker: AGENTEBC_DEEPSEEK_API_KEY es obligatorio "
                "con AGENTEBC_WORKER_AI_PROVIDER=deepseek"
            )
        return ChatCompletionClient(
            settings.deepseek_url or "https://api.deepseek.com",
            model=settings.deepseek_model or "deepseek-chat",
            provider="deepseek",
            api_key=settings.deepseek_api_key,
            timeout_seconds=settings.request_timeout_seconds,
        )
    if settings.ai_provider in {"deepseek_web", "google_ai_web"}:
        raise ValueError(
            "La IA del consultor es web (deepseek_web/google_ai_web). "
            "Para el resumen del informe del worker configure "
            "AGENTEBC_WORKER_AI_PROVIDER=lm_studio y "
            "AGENTEBC_WORKER_LM_STUDIO_URL (p. ej. http://127.0.0.1:1234/v1)."
        )
    raise ValueError(
        "Informe worker: configure AGENTEBC_WORKER_AI_PROVIDER=lm_studio "
        "y LM Studio (AGENTEBC_WORKER_LM_STUDIO_URL o AGENTEBC_LM_STUDIO_URL)."
    )
