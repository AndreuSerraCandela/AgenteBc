from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry

from .job_spec import WorkerJobSpec
from .paths import WorkerPaths
from .presets import PresetStore, WorkerPreset, merge_preset_with_company, new_preset_id
from agentebc.documents import DocumentReader

from .natural_language import compile_phrase
from .preview import build_job_preview
from .pending import (
    load_pending_preview,
    pending_skill_id,
    read_pending_raw,
    write_pending_preview,
)
from .field_edits import describe_before_action_edits, spec_with_posting_date_mode
from .runner import run_job
from .skill_editor import register_skill_routes
from .skill_share import SkillShareStore
from .simple_portal import register_simple_portal_routes
from .skill_connection import settings_for_skill
from .skill_postrun import finalize_skill_batch, postrun_summary
from .skills import SkillStore
from .batch_report import format_report_plain_text

_PAGE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>AgenteBc Worker</title>
  <style>
    body { font-family: Segoe UI, sans-serif; max-width: 900px; margin: 24px auto; padding: 0 16px; }
    section { border: 1px solid #ccc; border-radius: 6px; padding: 16px; margin-bottom: 16px; }
    label { display: block; margin-top: 8px; font-weight: 600; }
    input, select, textarea { width: 100%; padding: 8px; box-sizing: border-box; }
    button { margin-top: 12px; padding: 10px 16px; background: #0067b8; color: #fff; border: 0; cursor: pointer; }
    pre { background: #f4f4f4; padding: 12px; overflow: auto; white-space: pre-wrap; }
    .error { color: #a80000; }
    .warn { background: #fff8e6; border-left: 4px solid #c19c00; padding: 10px; margin: 12px 0; }
    .ok { background: #dff6dd; border-left: 4px solid #107c10; padding: 10px; margin: 12px 0; }
    label.inline { display: flex; align-items: center; gap: 8px; font-weight: normal; margin-top: 10px; }
    label.inline input { width: auto; }
    #run-status { color: #555; font-style: italic; margin-top: 8px; min-height: 1.2em; }
  </style>
</head>
<body>
  <h1>AgenteBc Worker</h1>
  <p><a href="/portal"><strong>Modo usuario</strong></a> — solo skill y ejecutar.</p>
  <p>Vista previa de trabajos de registro. AgenteBc consultor no se modifica aquí.</p>
  <p><a href="/skills"><strong>Editor de skills</strong></a> — fecha registro, filtros OData, informe (también en el formulario de abajo).</p>

  <section>
    <h2>Skill (trabajo empaquetado)</h2>
    <form method="post" action="/preview-skill">
      <label>Skill</label>
      <select name="skill_id" required>
        <option value="">— Seleccione —</option>
        {% for s in skills %}
        <option value="{{ s.id }}">{{ s.label }}</option>
        {% endfor %}
      </select>
      <label>Empresa <span class="hint" style="font-weight:normal;">(si el skill no la trae)</span></label>
      <input name="company_override" placeholder="Opcional">
      <label><strong>Antes de acción:</strong> Fecha registro en ficha BC</label>
      <select name="posting_date_before_register">
        <option value="">Usar lo guardado en el skill</option>
        <option value="today">Poner fecha de hoy</option>
        <option value="end_of_month">Poner fin de mes en curso</option>
        <option value="none">No cambiar la fecha</option>
      </select>
      <p class="hint" style="font-size:13px;color:#555;">Evita errores de serie V-FAC+ cuando la fecha de la factura es antigua. Para dejarlo fijo en el skill: <a href="/skills">Editor de skills</a>.</p>
      <label class="inline"><input type="checkbox" name="dry_run" value="yes" checked> Solo simulación (dry run)</label>
      <button type="submit">Preview del skill</button>
    </form>
  </section>

  <section>
    <h2>Lenguaje natural</h2>
    <form method="post" action="/plan">
      <label>Instrucción</label>
      <textarea name="phrase" rows="3" placeholder="Registrar las facturas de venta de Malla Publicidad de septiembre"></textarea>
      <label>Empresa (si no va en la frase)</label>
      <input name="company_override" placeholder="Opcional">
      <label class="inline"><input type="checkbox" name="dry_run" value="yes" checked> Solo simulación (dry run)</label>
      <button type="submit">Compilar y preview</button>
    </form>
  </section>

  <section>
    <h2>Nuevo preview (manual / preset)</h2>
    <form method="post" action="/preview">
      <label>Preset (opcional)</label>
      <select name="preset_id">
        <option value="">— Manual —</option>
        {% for p in presets %}
        <option value="{{ p.id }}">{{ p.label }}</option>
        {% endfor %}
      </select>
      <label>Empresa</label>
      <input name="company" required placeholder="Nombre empresa BC">
      <label>Tipo (si manual)</label>
      <input name="type_id" placeholder="sales_invoice">
      <label>Acción (si manual)</label>
      <input name="action_id" placeholder="registrar_factura">
      <label>Filtro fecha dinámico</label>
      <select name="date_dynamic">
        <option value="month_to_today">Mes en curso hasta hoy</option>
        <option value="current_month">Mes en curso (fin de mes)</option>
        <option value="current_year">Año en curso</option>
      </select>
      <label class="inline"><input type="checkbox" name="dry_run" value="yes" checked> Solo simulación (dry run)</label>
      <button type="submit">Generar preview</button>
    </form>
  </section>

  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  {% if saved_message %}<p>{{ saved_message }}</p>{% endif %}
  {% if preview %}
  <section>
    <h2>Preview</h2>
    <pre>{{ preview.summary }}</pre>
    {% if preview.sample_numbers %}
    <p><strong>Muestra:</strong> {{ preview.sample_numbers | join(', ') }}</p>
    {% endif %}
    <form method="post" action="/save-preset">
      <label>Nombre para guardar preset</label>
      <input name="preset_label" placeholder="Registrar ventas mes (Malla)">
      <button type="submit">Guardar preset (usa último preview)</button>
    </form>
    <form method="post" action="/run" id="run-form" onsubmit="document.getElementById('run-status').textContent='Procesando… (simulación: segundos; registro real en BC: mucho más)';">
      <p class="warn">Sin la segunda casilla solo <strong>simula</strong> el lote (no abre BC). Con «Ejecutar de verdad» Playwright registrará cada factura (puede tardar).</p>
      <label class="inline"><input type="checkbox" name="confirm" value="yes" required> Confirmo que el preview es correcto</label>
      <label class="inline"><input type="checkbox" name="execute_real" value="yes"> Ejecutar de verdad en Business Central</label>
      <label class="inline"><input type="checkbox" name="send_report" value="yes" checked> Tras el lote: informe + IA + correo (skill)</label>
      <button type="submit">Ejecutar trabajo</button>
      <p id="run-status"></p>
    </form>
  </section>
  {% endif %}
  {% if run_summary %}
  <section id="resultado">
    <h2>Resultado</h2>
    <p class="ok">{{ run_summary }}</p>
    {% if report_text %}
    <details open>
      <summary>Informe del skill</summary>
      <pre>{{ report_text }}</pre>
    </details>
    {% endif %}
    {% if run_result %}
    <details>
      <summary>Detalle JSON ejecución</summary>
      <pre>{{ run_result }}</pre>
    </details>
    {% endif %}
  </section>
  {% endif %}
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)
    worker_paths = WorkerPaths.resolve()
    worker_paths.ensure_dirs()

    def registry() -> DocumentTypeRegistry:
        return DocumentTypeRegistry(worker_paths.app.document_types_file)

    def store() -> PresetStore:
        return PresetStore(
            worker_paths.presets_file,
            bundled=worker_paths.bundled_presets_file,
        )

    def skill_store() -> SkillStore:
        return SkillStore(
            worker_paths.user_skills_dir,
            bundled_dirs=worker_paths.bundled_skills_dirs,
        )

    share_store = SkillShareStore()

    register_skill_routes(
        app,
        worker_paths=worker_paths,
        registry=registry,
        share_store=share_store,
    )

    register_simple_portal_routes(
        app,
        worker_paths=worker_paths,
        registry=registry,
        skill_store=skill_store,
        inbox_count_fn=lambda: len(share_store.list_pending()),
    )

    @app.get("/")
    def index():
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=None,
            error=None,
            saved_message=None,
            run_result=None,
            run_summary=None,
            report_text=None,
        )

    @app.post("/plan")
    def plan_route():
        err = None
        preview_obj = None
        compile_info = None
        try:
            phrase = request.form.get("phrase", "").strip()
            settings = Settings.from_environment()
            reg = registry()
            companies = _list_companies(settings)
            compiled = compile_phrase(
                phrase,
                reg,
                companies=companies,
                default_company=settings.company,
                settings=settings,
            )
            spec = compiled.spec
            override = request.form.get("company_override", "").strip()
            if override:
                data = spec.as_dict()
                data["company"] = override
                spec = WorkerJobSpec.from_dict(data)
            spec.validate_against_registry(reg)
            if request.form.get("dry_run") != "yes":
                data = spec.as_dict()
                data["dry_run"] = False
                spec = WorkerJobSpec.from_dict(data)
            client = BusinessCentralReadClient(settings)
            preview_obj = build_job_preview(reg, spec, client=client)
            compile_info = compiled.as_dict()
            worker_paths.pending_preview_file.write_text(
                json.dumps(preview_obj.as_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            err = str(exc)
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=preview_obj,
            error=err,
            saved_message=_compile_banner(compile_info) if compile_info else None,
            run_result=None,
            run_summary=None,
            report_text=None,
        )

    @app.post("/preview-skill")
    def preview_skill_route():
        err = None
        preview_obj = None
        skill_id = ""
        try:
            skill_id = request.form.get("skill_id", "").strip()
            skill = skill_store().get(skill_id)
            dry = request.form.get("dry_run") == "yes"
            company_override = request.form.get("company_override", "").strip()
            from .skill_connection import resolve_skill_company

            company = resolve_skill_company(skill, override=company_override)
            if not company:
                raise ValueError(
                    "Indique empresa (el skill no la define en spec ni connection)."
                )
            spec = WorkerJobSpec.from_dict(
                {**skill.to_job_spec(dry_run=dry).as_dict(), "company": company}
            )
            posting_mode = request.form.get("posting_date_before_register", "").strip()
            if posting_mode:
                spec = spec_with_posting_date_mode(spec, posting_mode)
            reg = registry()
            spec.validate_against_registry(reg)
            settings = settings_for_skill(Settings.from_environment(), skill)
            client = BusinessCentralReadClient(settings)
            preview_obj = build_job_preview(reg, spec, client=client)
            extra = describe_before_action_edits(spec)
            if extra:
                from dataclasses import replace

                preview_obj = replace(
                    preview_obj,
                    summary=preview_obj.summary + "\n" + extra,
                )
            payload = preview_obj.as_dict()
            payload["skill_id"] = skill.id
            write_pending_preview(worker_paths.pending_preview_file, payload)
        except Exception as exc:
            err = str(exc)
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=preview_obj,
            error=err,
            saved_message=f"Preview del skill «{skill_id}» (skill_id guardado para informe).",
            run_result=None,
            run_summary=None,
            report_text=None,
        )

    @app.post("/preview")
    def preview_route():
        err = None
        preview_obj = None
        try:
            spec = _spec_from_form(request.form, store())
            settings = Settings.from_environment()
            client = BusinessCentralReadClient(settings)
            preview_obj = build_job_preview(registry(), spec, client=client)
            worker_paths.pending_preview_file.write_text(
                json.dumps(preview_obj.as_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            err = str(exc)
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=preview_obj,
            error=err,
            saved_message=None,
            run_result=None,
            run_summary=None,
            report_text=None,
        )

    @app.post("/save-preset")
    def save_preset():
        err = None
        saved_message = None
        preview_obj = load_pending_preview(worker_paths.pending_preview_file)
        try:
            if preview_obj is None:
                raise ValueError("Genere un preview antes de guardar")
            spec_data = preview_obj.spec.as_dict()
            spec_data["company"] = ""
            spec = WorkerJobSpec.from_dict(spec_data, require_company=False)
            label = request.form.get("preset_label", "").strip()
            if not label:
                raise ValueError("Indique un nombre para el preset")
            preset = WorkerPreset(id=new_preset_id(label), label=label, spec=spec)
            store().save(preset)
            saved_message = f"Preset guardado: {preset.id}"
        except Exception as exc:
            err = str(exc)
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=preview_obj,
            error=err,
            saved_message=saved_message,
            run_result=None,
            run_summary=None,
            report_text=None,
        )

    @app.post("/run")
    def run_route():
        preview_obj = load_pending_preview(worker_paths.pending_preview_file)
        err = None
        run_result = None
        run_summary = None
        report_text = None
        if request.form.get("confirm") != "yes":
            err = "Debe confirmar que el preview es correcto."
        elif preview_obj is None:
            err = "No hay preview pendiente. Genere uno antes de ejecutar."
        else:
            spec = preview_obj.spec
            if request.form.get("execute_real") == "yes":
                data = spec.as_dict()
                data["dry_run"] = False
                spec = WorkerJobSpec.from_dict(data)
            try:
                pending_raw = read_pending_raw(worker_paths.pending_preview_file)
                skill_id = pending_skill_id(pending_raw)
                settings = Settings.from_environment()
                if skill_id:
                    settings = settings_for_skill(
                        settings,
                        skill_store().get(skill_id),
                    )
                result = run_job(
                    settings,
                    registry(),
                    spec,
                    reports_dir=worker_paths.app.reports_dir,
                )
                run_summary = _format_run_summary(result)
                run_result = json.dumps(
                    result.as_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
                want_mail = request.form.get("send_report") == "yes"
                if skill_id or want_mail:
                    if skill_id:
                        skill = skill_store().get(skill_id)
                    else:
                        skill = skill_store().get(
                            "malla_publicidad_facturar_ventas"
                        )
                    has_errors = any(
                        item.outcome == "error" for item in result.outcomes
                    )
                    batch_report = finalize_skill_batch(
                        settings,
                        skill,
                        result,
                        reports_dir=worker_paths.batch_reports_dir,
                        send_email=want_mail,
                        run_llm=want_mail or has_errors,
                    )
                    report_text = format_report_plain_text(batch_report)
                    run_summary = (
                        f"{run_summary} · {postrun_summary(batch_report)}"
                    )
                    if want_mail and not skill_id:
                        run_summary += (
                            " · Aviso: preview no era de un skill; "
                            "use «Preview del skill» para enlazar informe/correo."
                        )
            except Exception as exc:
                err = str(exc)
        return render_template_string(
            _PAGE,
            presets=store().all(),
            skills=skill_store().all(),
            preview=preview_obj,
            error=err,
            saved_message=None,
            run_result=run_result,
            run_summary=run_summary,
            report_text=report_text,
        )

    @app.get("/api/filters")
    def api_filters():
        return jsonify(
            {
                "dynamic_filters": [
                    "month_to_today",
                    "current_month",
                    "current_year",
                ],
            }
        )

    return app


def _list_companies(settings: Settings) -> tuple[str, ...]:
    try:
        return tuple(DocumentReader(BusinessCentralReadClient(settings)).list_companies())
    except Exception:
        fallback = (settings.company or "").strip()
        return (fallback,) if fallback else ()


def _format_run_summary(result) -> str:
    outcomes = result.outcomes
    total = len(outcomes)
    if result.dry_run:
        return (
            f"Simulación completada: {total} documento(s) en el lote. "
            "No se abrió Business Central. Para registrar de verdad, "
            "marque «Ejecutar de verdad» y vuelva a pulsar Ejecutar."
        )
    ok = sum(1 for o in outcomes if o.outcome == "success")
    failed = sum(1 for o in outcomes if o.outcome == "error")
    skipped = sum(1 for o in outcomes if o.outcome == "skipped")
    parts = [
        f"Registro real terminado: {ok} correcto(s), {failed} error(es), "
        f"{skipped} omitida(s), {total} en total."
    ]
    errors = [o for o in outcomes if o.outcome == "error"][:5]
    if errors:
        samples = "; ".join(f"{o.number}: {o.error}" for o in errors)
        parts.append(f"Primeros errores: {samples}")
    return " ".join(parts)


def _compile_banner(compile_info: dict) -> str:
    method = compile_info.get("method", "?")
    notes = compile_info.get("notes") or []
    extra = f" — {'; '.join(notes)}" if notes else ""
    return f"Compilado ({method}){extra}"


def _spec_from_form(form, preset_store: PresetStore) -> WorkerJobSpec:
    company = form.get("company", "").strip()
    preset_id = form.get("preset_id", "").strip()
    dry_run = form.get("dry_run") == "yes"
    if preset_id:
        spec = merge_preset_with_company(preset_store.get(preset_id), company)
    else:
        payload = {
            "company": company,
            "type_id": form.get("type_id", "").strip(),
            "action_id": form.get("action_id", "").strip(),
            "dry_run": dry_run,
            "limit": 200,
            "date_filter": {
                "field": "posting_date",
                "dynamic": form.get("date_dynamic", "current_month"),
            },
        }
        spec = WorkerJobSpec.from_dict(payload)
    if dry_run != spec.dry_run:
        data = spec.as_dict()
        data["dry_run"] = dry_run
        spec = WorkerJobSpec.from_dict(data)
    spec.validate_against_registry(
        DocumentTypeRegistry(WorkerPaths.resolve().app.document_types_file)
    )
    return spec


def main(host: str = "127.0.0.1", port: int = 8766) -> None:
    WorkerPaths.resolve().ensure_dirs()
    create_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
