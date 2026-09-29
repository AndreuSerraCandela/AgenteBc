from __future__ import annotations

import calendar
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from agentebc.config import Settings
from agentebc.document_types import DocumentTypeDefinition, DocumentTypeRegistry
from agentebc.llm_conclusions import ChatCompletionClient, build_llm_client

from .dynamic_filters import DYNAMIC_FILTER_IDS
from .job_spec import WorkerJobSpec

_MENTION_PATTERN = re.compile(r"@([a-z][a-z0-9_-]{1,49})", re.IGNORECASE)

_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_SYSTEM_PROMPT = (
    "Eres un compilador de trabajos para Business Central. "
    "Respondes únicamente con un objeto JSON válido, sin markdown ni texto extra."
)


@dataclass(frozen=True, slots=True)
class CompileResult:
    spec: WorkerJobSpec
    method: str
    phrase: str
    notes: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "phrase": self.phrase,
            "notes": list(self.notes),
            "ambiguities": list(self.ambiguities),
            "spec": self.spec.as_dict(),
        }


def compile_phrase(
    phrase: str,
    registry: DocumentTypeRegistry,
    *,
    companies: tuple[str, ...] = (),
    default_company: str | None = None,
    settings: Settings | None = None,
    reference_date: date | None = None,
    prefer_llm: bool = False,
) -> CompileResult:
    text = phrase.strip()
    if not text:
        raise ValueError("La frase no puede estar vacía")
    ref = reference_date or date.today()

    if prefer_llm:
        if settings is None or not settings.ai_enabled:
            raise ValueError(
                "prefer_llm requiere IA configurada (lm_studio o deepseek API)"
            )
        if settings.ai_provider in {"deepseek_web", "google_ai_web"}:
            raise ValueError(
                "El plan por lenguaje natural requiere lm_studio o deepseek API, "
                "no deepseek_web ni google_ai_web"
            )
        return _compile_with_llm(text, registry, companies, settings, ref)

    rules_result = _compile_with_rules(
        text, registry, companies, ref, default_company=default_company
    )
    if rules_result is not None:
        return rules_result

    if settings is not None and settings.ai_enabled:
        if settings.ai_provider in {"deepseek_web", "google_ai_web"}:
            raise ValueError(
                "No se pudo interpretar la frase con reglas. Configure lm_studio o "
                "deepseek API para compilación asistida por IA."
            )
        return _compile_with_llm(text, registry, companies, settings, ref)

    raise ValueError(
        "No se pudo interpretar la frase. Sea más explícito (empresa, tipo de "
        "documento, acción registrar, periodo) o configure IA (lm_studio/deepseek)."
    )


def _compile_with_rules(
    phrase: str,
    registry: DocumentTypeRegistry,
    companies: tuple[str, ...],
    reference: date,
    *,
    default_company: str | None = None,
) -> CompileResult | None:
    normalized = _normalize(phrase)
    mentions = {m.casefold() for m in _MENTION_PATTERN.findall(phrase)}

    type_id = _mention_type(mentions) or _infer_type_id(normalized)
    action_id = _mention_action(mentions, registry, type_id) or _infer_action_id(
        normalized, registry, type_id
    )
    company = _match_company(phrase, companies) or _optional_company(default_company)
    if not company and len(companies) == 1:
        company = companies[0]
    date_filter = _infer_date_filter(normalized, reference)
    dry_run = not _wants_real_execution(normalized)

    missing: list[str] = []
    if not company:
        missing.append("empresa")
    if not type_id:
        missing.append("tipo de documento")
    if not action_id:
        missing.append("acción")
    if missing:
        return None

    assert type_id and action_id and company
    payload: dict[str, Any] = {
        "company": company,
        "type_id": type_id,
        "action_id": action_id,
        "limit": 200,
        "dry_run": dry_run,
        "on_error": "report_and_continue",
    }
    if date_filter:
        payload["date_filter"] = date_filter

    spec = WorkerJobSpec.from_dict(payload)
    notes: list[str] = []
    if date_filter is None:
        notes.append("Sin filtro de fecha; acote el periodo si hace falta.")
    if dry_run:
        notes.append("Modo simulación (dry_run). Diga «ejecutar» o «real» para desactivarlo.")
    return CompileResult(
        spec=spec,
        method="rules",
        phrase=phrase,
        notes=tuple(notes),
    )


def _compile_with_llm(
    phrase: str,
    registry: DocumentTypeRegistry,
    companies: tuple[str, ...],
    settings: Settings,
    reference: date,
) -> CompileResult:
    client = build_llm_client(settings)
    if not isinstance(client, ChatCompletionClient):
        raise ValueError("Proveedor de IA no compatible con compilación JSON")

    catalog = _catalog_for_prompt(registry)
    company_hint = settings.company or ""
    user_prompt = f"""Convierte la instrucción del usuario en un JobSpec JSON.

Fecha de referencia (mes/año en curso): {reference.isoformat()}
Empresa por defecto si no se nombra otra: {company_hint or "(ninguna)"}
Empresas conocidas en BC: {json.dumps(list(companies), ensure_ascii=False)}

Catálogo (solo puede usar type_id y action_id listados):
{catalog}

Filtros dinámicos de fecha permitidos: {json.dumps(sorted(DYNAMIC_FILTER_IDS))}
Campo de fecha habitual: posting_date (salvo que el catálogo indique otro)

Esquema JSON obligatorio:
{{
  "company": "string",
  "type_id": "string",
  "action_id": "string",
  "date_filter": null | {{
    "field": "posting_date",
    "dynamic": "current_month" | "current_year"
  }} | {{
    "field": "posting_date",
    "from": "YYYY-MM-DD",
    "to": "YYYY-MM-DD"
  }},
  "limit": 200,
  "dry_run": true,
  "on_error": "report_and_continue"
}}

Reglas:
- dry_run true salvo que el usuario pida ejecutar de verdad en BC.
- Si menciona un mes por nombre (ej. septiembre), use from/to de ese mes; año explícito o {reference.year}.
- «Mes en curso» → dynamic current_month; «año en curso» → current_year.
- No invente ids que no estén en el catálogo.

Instrucción del usuario:
{text}
"""
    raw = client.complete(user_prompt, _SYSTEM_PROMPT)
    data = _extract_json_object(raw)
    spec = WorkerJobSpec.from_dict(data)
    spec.validate_against_registry(registry)
    return CompileResult(
        spec=spec,
        method="llm",
        phrase=phrase,
        notes=(f"Compilado con {client.provider}/{client.model}",),
    )


def _catalog_for_prompt(registry: DocumentTypeRegistry) -> str:
    lines: list[str] = []
    for definition in registry.all():
        actions = ", ".join(
            f"{action.id} ({action.label})" for action in definition.actions
        )
        lines.append(
            f"- type_id={definition.id} label={definition.label!r} actions: {actions}"
        )
    return "\n".join(lines) or "(catálogo vacío)"


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("La IA no devolvió un objeto JSON")
    return data


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _mention_type(mentions: set[str]) -> str | None:
    aliases = {
        "sales_invoice": "sales_invoice",
        "facturas_venta": "sales_invoice",
        "factura_venta": "sales_invoice",
        "facturas_ventas": "sales_invoice",
        "purchase_invoice": "purchase_invoice",
        "facturas_compra": "purchase_invoice",
        "factura_compra": "purchase_invoice",
    }
    for mention in mentions:
        mapped = aliases.get(mention)
        if mapped:
            return mapped
    return None


def _mention_action(
    mentions: set[str],
    registry: DocumentTypeRegistry,
    type_id: str | None,
) -> str | None:
    if not mentions:
        return None
    if type_id:
        try:
            definition = registry.get(type_id)
            for action in definition.actions:
                if action.id.casefold() in mentions:
                    return action.id
        except KeyError:
            pass
    for mention in mentions:
        if mention.startswith("registrar"):
            return mention if _action_exists(registry, mention) else None
    return None


def _action_exists(registry: DocumentTypeRegistry, action_id: str) -> bool:
    for definition in registry.all():
        for action in definition.actions:
            if action.id == action_id:
                return True
    return False


def _infer_type_id(normalized: str) -> str | None:
    if "factura" in normalized and "venta" in normalized:
        return "sales_invoice"
    if "factura" in normalized and "compra" in normalized:
        return "purchase_invoice"
    if "venta" in normalized and "registr" in normalized:
        return "sales_invoice"
    return None


def _infer_action_id(
    normalized: str,
    registry: DocumentTypeRegistry,
    type_id: str | None,
) -> str | None:
    if "registr" not in normalized and "register" not in normalized:
        return None
    if not type_id:
        return None
    try:
        definition = registry.get(type_id)
    except KeyError:
        return None
    for action in definition.actions:
        if action.id == "registrar_factura":
            return action.id
    for action in definition.actions:
        if "registrar" in _normalize(action.id) or _normalize(action.label) == "registrar":
            return action.id
    return None


def _match_company(phrase: str, companies: tuple[str, ...]) -> str | None:
    if not companies:
        return None
    phrase_fold = phrase.casefold()
    best: str | None = None
    best_len = 0
    for name in companies:
        candidate = name.strip()
        if not candidate:
            continue
        if candidate.casefold() in phrase_fold and len(candidate) > best_len:
            best = candidate
            best_len = len(candidate)
    return best


def _infer_date_filter(normalized: str, reference: date) -> dict[str, Any] | None:
    if "mes en curso" in normalized or "del mes" in normalized or "este mes" in normalized:
        return {"field": "posting_date", "dynamic": "current_month"}
    if "ano en curso" in normalized:
        return {"field": "posting_date", "dynamic": "current_year"}
    if "del ano" in normalized or "este ano" in normalized:
        return {"field": "posting_date", "dynamic": "current_year"}

    year_match = re.search(r"\b(20\d{2})\b", normalized)
    year = int(year_match.group(1)) if year_match else reference.year

    for name, month in _MONTHS.items():
        if name not in normalized:
            continue
        last = calendar.monthrange(year, month)[1]
        return {
            "field": "posting_date",
            "from": date(year, month, 1).isoformat(),
            "to": date(year, month, last).isoformat(),
        }
    return None


def _optional_company(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text or None


def _wants_real_execution(normalized: str) -> bool:
    markers = (
        "ejecutar de verdad",
        "ejecucion real",
        "sin simulacion",
        "sin dry run",
        "modo real",
    )
    return any(marker in normalized for marker in markers)
