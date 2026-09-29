"""Diagnóstico: localizar PostingDate y modo edición en una factura BC."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.web_preview import (
    BusinessCentralWebPreview,
    _activate_edit_mode,
    _bc_field_locator,
    _page_is_in_edit_mode,
    _field_label_aliases,
    _set_bc_field_value,
)
from agentebc_worker.field_edits import format_bc_ui_date
from datetime import date
from agentebc_worker.field_edits import materialize_action_for_job
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.list_documents import list_documents_for_job


def main() -> int:
    number = sys.argv[1] if len(sys.argv) > 1 else "ML256899"
    settings = Settings.from_environment()
    registry = DocumentTypeRegistry(ROOT / "config/document_types.json")
    skill = json.loads(
        (ROOT / "worker/skills/malla_publicidad_facturar_ventas.skill.json").read_text(
            encoding="utf-8"
        )
    )
    spec = WorkerJobSpec.from_dict({**skill["spec"], "limit": 50, "dry_run": True})
    spec.validate_against_registry(registry)
    definition = registry.get(spec.type_id)
    client = BusinessCentralReadClient(settings)
    listed = list_documents_for_job(client, definition, spec)
    doc = next((d for d in listed.documents if d.number == number), None)
    if doc is None:
        from agentebc.documents import DocumentReference

        doc = DocumentReference(
            company=spec.company,
            kind="sales",
            number=number,
            document_type="Invoice",
            status="Open",
            system_id="",
            posting_date=None,
        )
    action = materialize_action_for_job(definition, spec)
    preview = BusinessCentralWebPreview(settings)
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    shot = out_dir / f"probe-{number}.png"

    from playwright.sync_api import sync_playwright
    from agentebc.browser import launch_browser

    url = preview._document_url(doc, definition)  # noqa: SLF001
    info: dict = {"url": url, "number": number}

    with sync_playwright() as pw:
        browser = launch_browser(pw, settings)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        preview._sign_in_if_needed(page)  # noqa: SLF001
        frame = preview._wait_for_document_frame(page, action)  # noqa: SLF001
        info["edit_mode_before"] = _page_is_in_edit_mode(frame)
        info["save_buttons"] = frame.get_by_role("button", name="Guardar").count()
        markers = []
        for label in (
            "Guardar",
            "Save",
            "Descartar",
            "Discard",
            "Descartar cambios",
            "Discard changes",
        ):
            btn = frame.get_by_role("button", name=label)
            try:
                n = btn.count()
                vis = n and btn.first.is_visible()
            except Exception:
                n, vis = 0, False
            if n:
                markers.append({"label": label, "count": n, "visible": vis})
        info["edit_markers"] = markers
        info["edit_like_buttons"] = frame.evaluate(
            """() => {
              const out = [];
              for (const el of document.querySelectorAll('button,[role=button]')) {
                const t = (el.getAttribute('title') || el.getAttribute('aria-label') || el.textContent || '').trim();
                if (!t) continue;
                const f = t.toLowerCase();
                if (!/(edit|editar|modificar|cambios|changes)/i.test(f)) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                out.push({text: t.slice(0,120), visible: !!(el.offsetParent), w: r.width, h: r.height});
              }
              return out.slice(0, 30);
            }"""
        )
        loc0 = _bc_field_locator(frame, "Fecha registro")
        if loc0 is not None:
            info["set_before_pencil"] = _set_bc_field_value(
                frame, loc0, format_bc_ui_date(date.today())
            )
        pencil = frame.locator('button[title*="Realizar cambios en la página" i]')
        info["pencil_count"] = pencil.count()
        if pencil.count():
            try:
                pencil.first.click(timeout=3_000)
                page.wait_for_timeout(1500)
                info["after_pencil_click"] = {
                    "edit_mode": _page_is_in_edit_mode(frame),
                    "guardar": frame.get_by_role("button", name="Guardar").count(),
                    "guardar_title": frame.locator('button[title*="Guardar" i]').count(),
                }
            except Exception as exc:
                info["after_pencil_click"] = str(exc)
        activated = _activate_edit_mode(page, frame)
        info["activate_edit_once"] = activated
        info["edit_mode_after"] = _page_is_in_edit_mode(frame)
        info["save_buttons_after"] = frame.get_by_role("button", name="Guardar").count()
        target_date = format_bc_ui_date(date.today())
        for label in _field_label_aliases("Fecha registro"):
            loc = _bc_field_locator(frame, label)
            entry: dict = {"label": label, "found": loc is not None}
            if loc is not None:
                try:
                    entry["tag"] = loc.evaluate("el => el.tagName")
                    entry["readonly"] = loc.get_attribute("readonly")
                    entry["aria_readonly"] = loc.get_attribute("aria-readonly")
                    entry["input_value"] = loc.input_value(timeout=500)
                except Exception as exc:
                    entry["read_error"] = str(exc)
                try:
                    entry["inner_text"] = loc.inner_text(timeout=500)[:80]
                except Exception:
                    pass
            info.setdefault("locators", []).append(entry)
            if loc is not None:
                info["set_posting_date"] = _set_bc_field_value(frame, loc, target_date)
        posting = frame.locator('[controlname="PostingDate"]')
        info["posting_control_count"] = posting.count()
        if posting.count():
            entry = {}
            try:
                entry["text"] = posting.first.inner_text(timeout=1000)[:120]
                inputs = posting.first.locator("input, [role=textbox], textarea")
                entry["inner_inputs"] = inputs.count()
                if inputs.count():
                    inp = inputs.first
                    entry["inp_readonly"] = inp.get_attribute("readonly")
                    entry["inp_value"] = inp.input_value(timeout=500)
            except Exception as exc:
                entry["error"] = str(exc)
            info["posting_control"] = entry
        page.screenshot(path=str(shot), full_page=True)
        info["screenshot"] = str(shot)
        browser.close()

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
