"""Ejecuta dos casos BC, diagnostica y pide conclusiones a LM Studio."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.evidence_enrichment import enrich_from_message, format_enrichments_for_prompt
from agentebc.diagnosis import DiagnosticService
from agentebc.document_types import DocumentTypeRegistry
from agentebc.documents import DocumentReader
from agentebc.license_catalog import ExtensionCatalog
from agentebc.models import Incident
from agentebc.web_preview import (
    BusinessCentralWebPreview,
    primary_preview_message,
)

ROOT = Path(__file__).resolve().parent
COMPANY = "Piscis Dos Tres Hache, S.L."
LM_STUDIO_URL = "http://192.168.10.238:1234/v1/chat/completions"
LM_MODEL = "qwen2.5-32b-instruct"

CASES = (
    {
        "name": "Contrato CTO02-P0001 -> Firmado",
        "type_id": "sales_contract",
        "action_id": "estado_firmado",
        "number": "CTO02-P0001",
    },
    {
        "name": "Factura P4941 -> Vista previa registro",
        "type_id": "sales_invoice",
        "action_id": "preview_posting",
        "number": "P4941",
    },
)


def _extension_catalog(settings: Settings) -> ExtensionCatalog | None:
    if settings.source_path is None or not settings.license_client:
        return None
    return ExtensionCatalog(
        settings.source_path,
        license_url=settings.license_url,
        license_token=settings.license_token,
        license_client=settings.license_client,
        request_timeout_seconds=settings.request_timeout_seconds,
    )


from agentebc.llm_conclusions import build_conclusion_prompt
from agentebc.sql_reader import SqlReadOnlyClient


def _ask_lm_studio(prompt: str, model: str = LM_MODEL) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un consultor experto en Business Central. "
                        "Responde de forma práctica y concreta."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1500,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        LM_STUDIO_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def run_case(settings: Settings, registry: DocumentTypeRegistry, case: dict) -> None:
    definition = registry.get(case["type_id"])
    action = definition.action(case["action_id"])
    document = DocumentReader(BusinessCentralReadClient(settings)).find_document(
        company=COMPANY,
        definition=definition,
        number=case["number"],
    )
    print(f"\n{'=' * 72}")
    print(f"CASO: {case['name']}")
    print(f"Documento: {document.number} | Fecha registro: {document.posting_date}")
    print("=" * 72)

    preview = BusinessCentralWebPreview(settings, reports_dir=ROOT / "reports").run(
        document,
        definition,
        action,
    )
    if not preview.messages:
        print("Sin mensajes de error detectados.")
        return

    message = primary_preview_message(preview.messages)
    diagnosis = DiagnosticService(
        settings.source_path,
        _extension_catalog(settings),
        alpackages_path=settings.alpackages_path,
        cache_dir=ROOT / ".cache",
    ).diagnose(
        Incident(
            error_text=message.description,
            document_number=document.number,
            company=document.company,
            call_stack=message.call_stack,
            metadata={
                "document_kind": document.kind,
                "status": document.status,
                "posting_date": document.posting_date,
                "context": message.context,
                "context_field": message.context_field,
                "source": message.source,
                "source_field": message.source_field,
            },
        )
    )

    sql_client = (
        SqlReadOnlyClient(settings.sql_connection_string)
        if settings.sql_connection_string
        else None
    )
    enrichment_items = enrich_from_message(message, document.company, sql_client)

    print("\n--- Evidencia BC ---")
    print(f"Error: {message.description}")
    print(f"Campo: {message.context_field} | Origen: {message.source_field}")
    if message.call_stack:
        print(f"Pila: {message.call_stack[:200]}")
    if enrichment_items:
        print(format_enrichments_for_prompt(enrichment_items))
    if diagnosis.source_matches:
        match = diagnosis.source_matches[0]
        print(f"Código: {match.path}:{match.line}")

    prompt = build_conclusion_prompt(
        case_label=case["name"],
        document=document,
        message=message,
        diagnosis=diagnosis,
        enrichments=enrichment_items,
    )
    print("\n--- Consultando LM Studio (%s) ---\n" % LM_MODEL)
    try:
        answer = _ask_lm_studio(prompt)
        print(answer)
    except urllib.error.URLError as exc:
        print(f"ERROR LM Studio: {exc}", file=sys.stderr)
        print("\n--- Prompt generado (primeros 1500 chars) ---")
        print(prompt[:1500])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = Settings.from_environment()
    registry = DocumentTypeRegistry(ROOT / "config" / "document_types.json")
    for case in CASES:
        run_case(settings, registry, case)


if __name__ == "__main__":
    main()
