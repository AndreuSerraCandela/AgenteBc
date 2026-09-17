"""Depuración interna del flujo compartir detalles."""
from pathlib import Path

from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.documents import DocumentReader
from agentebc.bc_client import BusinessCentralReadClient
from agentebc.web_preview import BusinessCentralWebPreview

settings = Settings.from_environment()
root = Path(__file__).resolve().parent
registry = DocumentTypeRegistry(root / "config" / "document_types.json")
definition = registry.get("sales_contract")
action = definition.action("estado_firmado")
document = DocumentReader(BusinessCentralReadClient(settings)).find_document(
    company="Piscis Dos Tres Hache, S.L.",
    definition=definition,
    number="CTO02-P0001",
)

result = BusinessCentralWebPreview(settings, reports_dir=root / "reports").run(
    document,
    definition,
    action,
)
for i, msg in enumerate(result.messages):
    print("MSG", i, msg.description[:100])
    print("  field", msg.context_field, "source_field", msg.source_field)
    print("  info", (msg.additional_information or "")[:300])
    print("  stack", (msg.call_stack or "")[:300])
