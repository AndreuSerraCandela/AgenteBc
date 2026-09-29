"""UI mínima del worker: elegir skill (y empresa si falta) y ejecutar."""
from __future__ import annotations

import json
from typing import Callable

from flask import Flask, render_template_string, request

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry

from .field_edits import (
    DEFAULT_POSTING_DATE_FIELD_LABEL,
    describe_before_action_edits,
    spec_with_posting_date_mode,
)
from .job_spec import WorkerJobSpec
from .paths import WorkerPaths
from .pending import write_pending_preview
from .preview import build_job_preview
from .runner import run_job
from .skill_connection import resolve_skill_company, settings_for_skill
from .skill_postrun import finalize_skill_batch, postrun_summary
from .batch_report import format_report_plain_text
from .skills import SkillStore

_PORTAL_PAGE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>AgenteBc · Registro</title>
  <style>
    body { font-family: Segoe UI, sans-serif; max-width: 520px; margin: 48px auto; padding: 0 20px; }
    h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
    p.lead { color: #444; margin-top: 0; }
    label { display: block; margin-top: 16px; font-weight: 600; }
    select, input { width: 100%; padding: 10px; box-sizing: border-box; font-size: 1rem; }
    button { margin-top: 24px; width: 100%; padding: 14px; font-size: 1.05rem;
             background: #0067b8; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
    button:disabled { opacity: 0.6; cursor: wait; }
    .error { color: #a80000; margin-top: 16px; }
    .ok { background: #dff6dd; border-left: 4px solid #107c10; padding: 12px; margin-top: 20px; white-space: pre-wrap; }
    .hint { font-size: 13px; color: #555; font-weight: normal; }
    nav.top { margin-bottom: 20px; font-size: 15px; }
    nav.top a { color: #0067b8; text-decoration: none; font-weight: 600; }
    nav.top a:hover { text-decoration: underline; }
    .skills-banner {
      background: #eef6ff; border: 1px solid #b4d6fa; border-radius: 6px;
      padding: 12px 14px; margin-bottom: 20px; font-size: 14px;
    }
    .skills-banner a { color: #0067b8; font-weight: 600; }
    .saved-banner {
      background: #dff6dd; border-left: 4px solid #107c10;
      padding: 10px 12px; margin-bottom: 16px; font-size: 14px;
    }
    footer { margin-top: 32px; font-size: 13px; color: #666; }
    footer a { color: #0067b8; }
    details pre { background: #f4f4f4; padding: 10px; overflow: auto; white-space: pre-wrap; }
  </style>
</head>
<body>
  <nav class="top">
    <a href="/portal">Registro</a>
    {% if share_configured %}
      · <a href="/skills/inbox">Skills ({{ inbox_count }})</a>
    {% endif %}
    · <a href="/">Modo consultor</a>
  </nav>
  <h1>Registro en Business Central</h1>
  <p class="lead">Elija el trabajo y pulse Ejecutar. Se registrarán las facturas del criterio del skill.</p>
  {% if saved_message %}<div class="saved-banner">{{ saved_message }}</div>{% endif %}
  {% if share_configured and inbox_count %}
  <div class="skills-banner">
    Hay {{ inbox_count }} skill(s) del consultor pendientes de descargar.
    <a href="/skills/inbox">Abrir Skills ({{ inbox_count }})</a>
  </div>
  {% endif %}

  <form method="post" action="{{ url_for('portal_run') }}" id="run-form"
        onsubmit="document.getElementById('go').disabled=true; document.getElementById('go').textContent='Ejecutando…';">
    <label>Trabajo (skill)</label>
    <select name="skill_id" required id="skill_id">
      <option value="">— Seleccione —</option>
      {% for s in skills %}
      <option value="{{ s.id }}" data-company="{{ s.company_hint }}"
        {% if form.skill_id == s.id %}selected{% endif %}>{{ s.label }}</option>
      {% endfor %}
    </select>

    <label id="company-label">Empresa
      <span class="hint" id="company-hint"></span>
    </label>
    <input name="company" id="company" value="{{ form.company }}" placeholder="Nombre en BC">

    <label id="posting-label">{{ posting_field_label }}
      <span class="hint">(en la ficha BC, antes de registrar)</span>
    </label>
    <select name="posting_date_before_register" id="posting_date">
      <option value="today" {% if form.posting_date == 'today' %}selected{% endif %}>Poner fecha de hoy</option>
      <option value="end_of_month" {% if form.posting_date == 'end_of_month' %}selected{% endif %}>Poner fin de mes en curso</option>
      <option value="skill" {% if form.posting_date == 'skill' %}selected{% endif %}>Usar lo definido en el skill</option>
      <option value="none" {% if form.posting_date == 'none' %}selected{% endif %}>No cambiar la fecha</option>
    </select>

    <button type="submit" id="go">Ejecutar registro</button>
  </form>

  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  {% if summary %}<div class="ok">{{ summary }}</div>{% endif %}
  {% if report_text %}
  <details open style="margin-top:16px;">
    <summary>Informe</summary>
    <pre>{{ report_text }}</pre>
  </details>
  {% endif %}

  <footer>
    <a href="/skills">Editor de skills</a>
    {% if share_configured %}
      · <a href="/skills/inbox">Skills ({{ inbox_count }})</a>
    {% endif %}
  </footer>
  <script>
    const sel = document.getElementById('skill_id');
    const company = document.getElementById('company');
    const hint = document.getElementById('company-hint');
    function syncCompany() {
      const opt = sel.options[sel.selectedIndex];
      const c = opt ? (opt.getAttribute('data-company') || '') : '';
      if (c) {
        company.value = c;
        company.readOnly = true;
        hint.textContent = '(definida en el skill)';
      } else {
        company.readOnly = false;
        hint.textContent = '(obligatoria si el skill no la trae)';
      }
    }
    sel.addEventListener('change', syncCompany);
    syncCompany();
  </script>
</body>
</html>
"""


def register_simple_portal_routes(
    app: Flask,
    *,
    worker_paths: WorkerPaths,
    registry: Callable[[], DocumentTypeRegistry],
    skill_store: Callable[[], SkillStore],
    inbox_count_fn: Callable[[], int] | None = None,
) -> None:
    @app.get("/portal")
    def portal_home():
        from .skill_share import share_portal_configured

        skill_id = request.args.get("skill_id", "").strip()
        saved = request.args.get("saved", "").strip()
        saved_message = None
        if saved == "skill":
            saved_message = "Skill descargado. Ya puede ejecutarlo abajo."
        return _render_portal(
            skill_store(),
            form={"skill_id": skill_id, "company": "", "posting_date": "today"},
            posting_field_label=DEFAULT_POSTING_DATE_FIELD_LABEL,
            error=None,
            summary=None,
            report_text=None,
            inbox_count=_inbox_count(inbox_count_fn),
            share_configured=share_portal_configured(),
            saved_message=saved_message,
        )

    @app.post("/portal/run")
    def portal_run():
        err = None
        summary = None
        report_text = None
        skill_id = request.form.get("skill_id", "").strip()
        company_input = request.form.get("company", "").strip()
        posting_mode = request.form.get("posting_date_before_register", "today").strip()
        form = {
            "skill_id": skill_id,
            "company": company_input,
            "posting_date": posting_mode or "today",
        }
        posting_label = DEFAULT_POSTING_DATE_FIELD_LABEL
        try:
            skill = skill_store().get(skill_id)
            posting_label = _posting_field_label(skill)
            company = resolve_skill_company(skill, override=company_input)
            if not company:
                raise ValueError(
                    "Indique la empresa BC. El skill no la define en spec ni en connection."
                )
            settings = settings_for_skill(Settings.from_environment(), skill)
            spec = WorkerJobSpec.from_dict(
                {**skill.to_job_spec(dry_run=False).as_dict(), "company": company}
            )
            apply_mode = posting_mode if posting_mode != "skill" else ""
            spec = spec_with_posting_date_mode(spec, apply_mode)
            reg = registry()
            spec.validate_against_registry(reg)
            client = BusinessCentralReadClient(settings)
            preview = build_job_preview(reg, spec, client=client)
            edit_note = describe_before_action_edits(spec)
            if edit_note:
                from dataclasses import replace

                preview = replace(
                    preview,
                    summary=preview.summary + "\n" + edit_note,
                )
            payload = preview.as_dict()
            payload["skill_id"] = skill.id
            write_pending_preview(worker_paths.pending_preview_file, payload)

            result = run_job(
                settings,
                reg,
                spec,
                reports_dir=worker_paths.app.reports_dir,
            )
            has_errors = any(item.outcome == "error" for item in result.outcomes)
            batch_report = finalize_skill_batch(
                settings,
                skill,
                result,
                reports_dir=worker_paths.batch_reports_dir,
                send_email=True,
                run_llm=has_errors,
            )
            summary = (
                f"{_run_line(result)} · {postrun_summary(batch_report)}"
            )
            report_text = format_report_plain_text(batch_report)
        except Exception as exc:
            err = str(exc)
        from .skill_share import share_portal_configured

        return _render_portal(
            skill_store(),
            form=form,
            error=err,
            summary=summary,
            report_text=report_text,
            inbox_count=_inbox_count(inbox_count_fn),
            posting_field_label=posting_label if skill_id else DEFAULT_POSTING_DATE_FIELD_LABEL,
            share_configured=share_portal_configured(),
            saved_message=None,
        )


def _render_portal(
    store: SkillStore,
    *,
    form: dict[str, str],
    error: str | None,
    summary: str | None,
    report_text: str | None,
    inbox_count: int,
    share_configured: bool,
    saved_message: str | None,
    posting_field_label: str = DEFAULT_POSTING_DATE_FIELD_LABEL,
):
    skills_view = []
    for skill in store.all():
        hint = resolve_skill_company(skill)
        skills_view.append(
            type("Row", (), {"id": skill.id, "label": skill.label, "company_hint": hint})()
        )
    return render_template_string(
        _PORTAL_PAGE,
        skills=skills_view,
        form=form,
        error=error,
        summary=summary,
        report_text=report_text,
        inbox_count=inbox_count,
        share_configured=share_configured,
        saved_message=saved_message,
        posting_field_label=posting_field_label,
    )


def _posting_field_label(skill) -> str:
    for step in skill.spec.before_action_field_edits:
        if step.field_label.strip():
            return step.field_label.strip()
    return DEFAULT_POSTING_DATE_FIELD_LABEL


def _run_line(result) -> str:
    t = result.totals if hasattr(result, "totals") else {}
    if isinstance(result.outcomes, tuple):
        ok = sum(1 for o in result.outcomes if o.outcome == "success")
        err = sum(1 for o in result.outcomes if o.outcome == "error")
        return f"Listo: {ok} registradas, {err} con error"
    return "Ejecución completada"


def _inbox_count(fn: Callable[[], int] | None) -> int:
    if fn is None:
        return 0
    try:
        return int(fn())
    except Exception:
        return 0
