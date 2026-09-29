"""Depuración paso a paso: fecha registro + (opcional) registrar."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.web_preview import (
    BusinessCentralWebPreview,
    _read_field_display_value,
    _bc_field_locator,
    _page_is_in_edit_mode,
)
from agentebc_worker.field_edits import format_bc_ui_date, materialize_action_for_job
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.list_documents import list_documents_for_job
from playwright.sync_api import sync_playwright
from agentebc.browser import launch_browser


def snap(page, name: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  captura: {path}")


def main() -> int:
    register = "--register" in sys.argv
    settings = Settings.load_fresh(ROOT / ".env")
    registry = DocumentTypeRegistry(ROOT / "config/document_types.json")
    skill = json.loads(
        (ROOT / "worker/skills/malla_publicidad_facturar_ventas.skill.json").read_text(
            encoding="utf-8"
        )
    )
    spec = WorkerJobSpec.from_dict(
        {**skill["spec"], "limit": 5, "dry_run": False}
    )
    spec.validate_against_registry(registry)
    definition = registry.get(spec.type_id)
    action = materialize_action_for_job(definition, spec)
    print("field_edits en acción:", [(s.field_label, s.value) for s in action.field_edits])
    client = BusinessCentralReadClient(settings)
    listed = list_documents_for_job(client, definition, spec)
    if not listed.documents:
        print("No hay facturas en OData con el filtro del skill.")
        return 1
    doc = listed.documents[0]
    target = format_bc_ui_date(date.today())
    print(f"Documento: {doc.number}  fecha objetivo: {target}")
    preview = BusinessCentralWebPreview(settings, reports_dir=ROOT / "reports")
    out = ROOT / "reports" / f"debug-{doc.number}"
    url = preview._document_url(doc, definition)  # noqa: SLF001
    print("URL:", url)

    with sync_playwright() as pw:
        browser = launch_browser(pw, settings)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        preview._sign_in_if_needed(page)  # noqa: SLF001
        frame = preview._wait_for_document_frame(page, action)  # noqa: SLF001
        preview._dismiss_bc_message_dialogs(page)  # noqa: SLF001
        snap(page, "01-loaded", out)
        print("edit_mode:", _page_is_in_edit_mode(frame))
        print("Fecha registro (antes):", _read_field_display_value(frame, "Fecha registro"))

        if action.field_edits:
            msgs = preview._apply_field_edits(frame, action.field_edits)  # noqa: SLF001
            snap(page, "02-after-field-edits", out)
            print("mensajes validación:", msgs)
            print("Fecha registro (tras edit):", _read_field_display_value(frame, "Fecha registro"))
            if not msgs:
                preview._commit_page_edits(page, frame)  # noqa: SLF001
                snap(page, "03-after-save", out)
                print("Fecha registro (tras guardar):", _read_field_display_value(frame, "Fecha registro"))

        controls = frame.evaluate(
            """() => Array.from(document.querySelectorAll('[controlname]'))
            .slice(0,40)
            .map(el => ({cn: el.getAttribute('controlname'), text: (el.innerText||'').slice(0,60)}))"""
        )
        print("controlnames muestra:", json.dumps(controls[:15], ensure_ascii=False))

        if register:
            preview._click_action(frame, action)  # noqa: SLF001
            snap(page, "04-after-register-click", out)
        else:
            print("(Sin --register: no se pulsa Registrar)")

        snap(page, "99-final", out)
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
