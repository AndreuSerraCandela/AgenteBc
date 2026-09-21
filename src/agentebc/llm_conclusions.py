from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .documents import DocumentReference
from .evidence_enrichment import EvidenceItem, format_enrichments_for_prompt
from .models import DiagnosticReport
from .web_preview import PreviewMessage

if TYPE_CHECKING:
    from .config import Settings

from .deepseek_web import DeepSeekWebClient, DeepSeekWebError
from .google_ai_web import GoogleAiWebClient, GoogleAiWebError

_WEB_AI_PROVIDERS = frozenset({"deepseek_web", "google_ai_web"})

_SYSTEM_PROMPT = (
    "Eres un consultor experto en Business Central. "
    "Responde de forma práctica y concreta."
)


@dataclass(frozen=True, slots=True)
class AiConclusionResult:
    model: str
    provider: str
    system_prompt: str
    user_prompt: str
    conclusion: str
    error: str | None = None
    external_view: bool = False
    external_url: str | None = None
    external_cdp_available: bool = False
    external_label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_conclusion_prompt(
    *,
    case_label: str,
    document: DocumentReference,
    message: PreviewMessage,
    diagnosis: DiagnosticReport,
    enrichments: tuple[EvidenceItem, ...] = (),
) -> str:
    excerpts = "\n\n".join(
        f"--- {match.path}:{match.line} ---\n{match.excerpt}"
        for match in diagnosis.source_matches[:3]
    )
    enrichment_block = format_enrichments_for_prompt(enrichments)
    return f"""Eres consultor senior de Microsoft Dynamics 365 Business Central y AL.

Analiza este incidente y responde en español con:
1. **Causa raíz probable** (1 párrafo claro)
2. **Qué debe hacer el usuario funcional** (pasos concretos)
3. **Qué debe revisar el consultor/desarrollador** (si aplica)
4. **Opciones de solución**, ordenadas de menor a mayor impacto
5. **Cómo verificar** que quedó resuelto
6. **Nivel de confianza** (alta/media/baja) y qué dato falta si no es alta

No inventes objetos, líneas ni campos que no aparezcan abajo.
Usa el contexto BC, la evidencia adicional y la pila de llamadas como fuentes
principales. Si falta evidencia, indícalo en lugar de suponer.

## Caso
{case_label}

## Documento
- Empresa: {document.company}
- Tipo: {document.kind}
- Número: {document.number}
- Estado: {document.status or '—'}
- Fecha de registro: {document.posting_date or 'Sin fecha'}

## Error observado
{message.description}

## Contexto BC
- Contexto: {message.context or '—'}
- Campo: {message.context_field or '—'}
- Origen: {message.source or '—'}
- Campo origen: {message.source_field or '—'}

## Información adicional
{message.additional_information or '—'}

## Pila de llamadas
{message.call_stack or '—'}

{enrichment_block}## Diagnóstico automático (referencia, puede ser genérico)
{diagnosis.summary}

## Extractos de código candidatos
{excerpts or '—'}
"""


class ChatCompletionClient:
    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        provider: str,
        api_key: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1"):
            self._chat_url = f"{normalized}/chat/completions"
        else:
            self._chat_url = f"{normalized}/v1/chat/completions"
        self._model = model
        self._provider = provider
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return self._provider

    def complete(self, user_prompt: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 1500,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self._chat_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(
            request,
            timeout=self._timeout_seconds,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]


LmStudioClient = ChatCompletionClient


def _default_deepseek_web_profile() -> Path:
    return Path.home() / ".agentebc" / "deepseek-profile"


def build_llm_client(
    settings: Settings,
) -> ChatCompletionClient | DeepSeekWebClient | GoogleAiWebClient:
    if settings.ai_provider == "google_ai_web":
        return GoogleAiWebClient(
            base_url=settings.google_ai_web_url or "https://www.google.com/ai",
            settings=settings,
            timeout_seconds=settings.deepseek_web_timeout_seconds,
            cdp_url=settings.ai_web_cdp_url,
        )
    if settings.ai_provider == "deepseek_web":
        return DeepSeekWebClient(
            chat_url=settings.deepseek_web_url or "https://chat.deepseek.com",
            profile_dir=(
                settings.deepseek_web_profile or _default_deepseek_web_profile()
            ),
            settings=settings,
            timeout_seconds=settings.deepseek_web_timeout_seconds,
            login_timeout_seconds=settings.deepseek_web_login_timeout_seconds,
            cdp_url=settings.ai_web_cdp_url,
        )
    if settings.ai_provider == "deepseek":
        return ChatCompletionClient(
            settings.deepseek_url or "https://api.deepseek.com",
            model=settings.deepseek_model or "deepseek-chat",
            provider="deepseek",
            api_key=settings.deepseek_api_key,
            timeout_seconds=settings.request_timeout_seconds,
        )
    if settings.ai_provider == "lm_studio":
        return ChatCompletionClient(
            settings.lm_studio_url or "",
            model=settings.lm_studio_model or "qwen2.5-32b-instruct",
            provider="lm_studio",
            timeout_seconds=settings.request_timeout_seconds,
        )
    raise ValueError("La IA no está configurada")


def request_ai_conclusion(
    client: ChatCompletionClient | DeepSeekWebClient | GoogleAiWebClient,
    *,
    case_label: str,
    document: DocumentReference,
    message: PreviewMessage,
    diagnosis: DiagnosticReport,
    enrichments: tuple[EvidenceItem, ...] = (),
) -> AiConclusionResult:
    user_prompt = build_conclusion_prompt(
        case_label=case_label,
        document=document,
        message=message,
        diagnosis=diagnosis,
        enrichments=enrichments,
    )
    if client.provider in _WEB_AI_PROVIDERS:
        external_url = getattr(client, "chat_url", None)
        external_label = getattr(client, "external_label", "IA")
        try:
            client.submit_prompt_only(user_prompt, _SYSTEM_PROMPT)
            error = None
            external_url = getattr(client, "chat_url", external_url)
        except (DeepSeekWebError, GoogleAiWebError, RuntimeError) as exc:
            error = str(exc)
        return AiConclusionResult(
            model=client.model,
            provider=client.provider,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            conclusion="",
            error=error,
            external_view=error is None,
            external_url=external_url if error is None else None,
            external_cdp_available=bool(getattr(client, "cdp_available", False)),
            external_label=external_label if error is None else None,
        )

    try:
        conclusion = client.complete(user_prompt, _SYSTEM_PROMPT)
        error = None
    except (
        urllib.error.URLError,
        TimeoutError,
        KeyError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        conclusion = ""
        error = str(exc)
    return AiConclusionResult(
        model=client.model,
        provider=client.provider,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        conclusion=conclusion,
        error=error,
    )
