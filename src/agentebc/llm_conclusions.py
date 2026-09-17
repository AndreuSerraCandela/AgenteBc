from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .documents import DocumentReference
from .evidence_enrichment import EvidenceItem, format_enrichments_for_prompt
from .models import DiagnosticReport
from .web_preview import PreviewMessage

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


class LmStudioClient:
    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1"):
            self._chat_url = f"{normalized}/chat/completions"
        else:
            self._chat_url = f"{normalized}/v1/chat/completions"
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

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
        request = urllib.request.Request(
            self._chat_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            request,
            timeout=self._timeout_seconds,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]


def request_ai_conclusion(
    client: LmStudioClient,
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
    try:
        conclusion = client.complete(user_prompt)
        error = None
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        conclusion = ""
        error = str(exc)
    return AiConclusionResult(
        model=client.model,
        provider="lm_studio",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        conclusion=conclusion,
        error=error,
    )
