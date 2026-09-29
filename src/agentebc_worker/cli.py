from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import ConfigurationError, Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.paths import AppPaths

from .job_spec import DateFilterSpec, WorkerJobSpec
from .natural_language import compile_phrase
from .paths import WorkerPaths
from .presets import PresetStore, WorkerPreset, merge_preset_with_company, new_preset_id
from .preview import build_job_preview
from .runner import run_job
from .pending import pending_skill_id, read_pending_raw
from .skill_postrun import finalize_skill_batch, postrun_summary
from .skills import SkillStore
from agentebc.documents import DocumentReader


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (ConfigurationError, KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentebc-worker",
        description="Worker autónomo de registro (preview, presets y ejecución)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser(
        "preview",
        help="Genera vista previa del trabajo (listado OData + resumen)",
    )
    _add_spec_args(preview)
    preview.add_argument(
        "--save-pending",
        action="store_true",
        help="Guarda el preview en worker/pending_preview.json para confirmar después",
    )
    preview.add_argument(
        "--reference-date",
        help="Fecha de referencia ISO (YYYY-MM-DD) para filtros dinámicos",
    )

    run = sub.add_parser("run", help="Ejecuta un trabajo confirmado")
    run.add_argument("--confirm", required=True, choices=["yes"])
    run.add_argument("--file", type=Path, help="JobSpec JSON")
    run.add_argument("--pending", action="store_true", help="Usar pending_preview.json")
    run.add_argument("--preset", help="Preset guardado")
    run.add_argument("--company", help="Empresa BC (obligatorio con --preset)")

    preset_list = sub.add_parser("preset-list", help="Lista presets (incluidos los predefinidos)")
    preset_save = sub.add_parser(
        "preset-save",
        help="Guarda un preset a partir de un JobSpec o pending preview",
    )
    preset_save.add_argument("--name", required=True, help="Etiqueta visible del preset")
    preset_save.add_argument("--id", help="Id estable (opcional; se genera si falta)")
    preset_save.add_argument("--file", type=Path, help="JobSpec JSON (sin company en preset)")
    preset_save.add_argument(
        "--from-pending",
        action="store_true",
        help="Usar spec de pending_preview.json",
    )

    serve = sub.add_parser("serve", help="UI web mínima del worker")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)

    filters = sub.add_parser("filters", help="Lista filtros dinámicos disponibles")

    plan = sub.add_parser(
        "plan",
        help="Compila lenguaje natural → JobSpec (reglas; IA si hace falta)",
    )
    plan.add_argument("phrase", help="Instrucción en español")
    plan.add_argument(
        "--llm",
        action="store_true",
        help="Forzar compilación con IA (lm_studio o deepseek API)",
    )
    plan.add_argument(
        "--preview",
        action="store_true",
        help="Tras compilar, generar vista previa OData",
    )
    plan.add_argument(
        "--save-pending",
        action="store_true",
        help="Guardar preview en pending_preview.json (requiere --preview)",
    )
    plan.add_argument(
        "--reference-date",
        help="Fecha de referencia ISO para mes/año en curso",
    )
    plan.add_argument(
        "--company",
        help="Empresa si la frase no la incluye (complemento)",
    )
    return parser


def _add_spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", type=Path, help="JobSpec JSON completo")
    parser.add_argument("--preset", help="Id de preset predefinido o guardado")
    parser.add_argument("--company", help="Empresa BC")
    parser.add_argument("--type-id", dest="type_id", help="type_id del catálogo")
    parser.add_argument("--action-id", dest="action_id", help="action_id")
    parser.add_argument(
        "--date-field",
        default="posting_date",
        help="Campo lógico de fecha (posting_date, etc.)",
    )
    parser.add_argument(
        "--date-dynamic",
        choices=["current_month", "current_year"],
        help="Filtro de fecha dinámico",
    )
    parser.add_argument("--date-from", help="Fecha inicio ISO")
    parser.add_argument("--date-to", help="Fecha fin ISO")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Equivalente a --no-dry-run en preview (solo informativo)",
    )


def _dispatch(args: argparse.Namespace) -> Any:
    worker_paths = WorkerPaths.resolve()
    worker_paths.ensure_dirs()
    app_paths = worker_paths.app
    registry = DocumentTypeRegistry(app_paths.document_types_file)
    store = PresetStore(
        worker_paths.presets_file,
        bundled=worker_paths.bundled_presets_file,
    )

    if args.command == "filters":
        return {
            "dynamic_filters": [
                {
                    "id": "current_month",
                    "label": "Mes en curso (calendario local)",
                },
                {
                    "id": "current_year",
                    "label": "Año en curso (calendario local)",
                },
            ]
        }

    if args.command == "preset-list":
        return [preset.as_dict() for preset in store.all()]

    if args.command == "preset-save":
        spec = _load_spec_for_preset_save(args, worker_paths)
        spec.validate_against_registry(registry)
        preset_id = args.id.strip() if args.id else new_preset_id(args.name)
        preset = WorkerPreset(id=preset_id, label=args.name.strip(), spec=spec)
        store.save(preset)
        return {"saved": preset.as_dict()}

    if args.command == "preview":
        settings = Settings.from_environment()
        spec = _resolve_spec(args, store)
        spec.validate_against_registry(registry)
        ref = _parse_reference_date(getattr(args, "reference_date", None))
        client = None
        try:
            client = BusinessCentralReadClient(settings)
        except ValueError:
            client = None
        preview = build_job_preview(
            registry,
            spec,
            client=client,
            reference_date=ref,
        )
        payload = preview.as_dict()
        if args.save_pending:
            worker_paths.pending_preview_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            payload["pending_saved"] = str(worker_paths.pending_preview_file)
        return payload

    if args.command == "run":
        if args.confirm != "yes":
            raise ValueError("Debe pasar --confirm yes para ejecutar")
        settings = Settings.from_environment()
        spec = _resolve_run_spec(args, worker_paths, store)
        spec.validate_against_registry(registry)
        result = run_job(
            settings,
            registry,
            spec,
            reports_dir=app_paths.reports_dir,
        )
        payload = result.as_dict()
        pending = read_pending_raw(worker_paths.pending_preview_file)
        skill_id = pending_skill_id(pending)
        if skill_id:
            store_skills = SkillStore(
                worker_paths.user_skills_dir,
                bundled_dirs=worker_paths.bundled_skills_dirs,
            )
            skill = store_skills.get(skill_id)
            report = finalize_skill_batch(
                settings,
                skill,
                result,
                reports_dir=worker_paths.batch_reports_dir,
                send_email=True,
            )
            payload["skill_report"] = report.as_dict()
            payload["skill_postrun_summary"] = postrun_summary(report)
        return payload

    if args.command == "serve":
        from .webapp import main as serve_main

        serve_main(host=args.host, port=args.port)
        return None

    if args.command == "plan":
        settings = Settings.from_environment()
        ref = _parse_reference_date(getattr(args, "reference_date", None))
        companies = _list_companies(settings)
        compiled = compile_phrase(
            args.phrase,
            registry,
            companies=companies,
            default_company=settings.company,
            settings=settings,
            reference_date=ref,
            prefer_llm=args.llm,
        )
        spec = compiled.spec
        if args.company:
            data = spec.as_dict()
            data["company"] = args.company.strip()
            spec = WorkerJobSpec.from_dict(data)
        spec.validate_against_registry(registry)
        payload: dict[str, Any] = compiled.as_dict()
        payload["spec"] = spec.as_dict()
        if args.preview:
            client = None
            try:
                client = BusinessCentralReadClient(settings)
            except ValueError:
                client = None
            preview = build_job_preview(
                registry,
                spec,
                client=client,
                reference_date=ref,
            )
            payload["preview"] = preview.as_dict()
            if args.save_pending:
                worker_paths.pending_preview_file.write_text(
                    json.dumps(preview.as_dict(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                payload["pending_saved"] = str(worker_paths.pending_preview_file)
        return payload

    raise ValueError(f"Comando desconocido: {args.command}")


def _list_companies(settings: Settings) -> tuple[str, ...]:
    try:
        reader = DocumentReader(BusinessCentralReadClient(settings))
        return tuple(reader.list_companies())
    except Exception:
        fallback = settings.company.strip() if settings.company else ""
        return (fallback,) if fallback else ()


def _resolve_spec(args: argparse.Namespace, store: PresetStore) -> WorkerJobSpec:
    if args.file:
        data = json.loads(args.file.read_text(encoding="utf-8"))
        if "spec" in data and "summary" in data:
            data = data["spec"]
        return WorkerJobSpec.from_dict(data)
    if args.preset:
        if not args.company:
            raise ValueError("--company es obligatorio con --preset")
        return merge_preset_with_company(store.get(args.preset), args.company)
    if args.type_id and args.action_id and args.company:
        date_filter = _date_filter_from_args(args)
        dry_run = not args.execute if args.execute else args.dry_run
        payload: dict[str, Any] = {
            "company": args.company,
            "type_id": args.type_id,
            "action_id": args.action_id,
            "limit": args.limit,
            "dry_run": dry_run,
        }
        if date_filter:
            payload["date_filter"] = _date_filter_dict(date_filter)
        return WorkerJobSpec.from_dict(payload)
    raise ValueError(
        "Indique --file, o --preset con --company, o --company --type-id --action-id"
    )


def _resolve_run_spec(
    args: argparse.Namespace,
    worker_paths: WorkerPaths,
    store: PresetStore,
) -> WorkerJobSpec:
    if args.pending:
        path = worker_paths.pending_preview_file
        if not path.is_file():
            raise ValueError("No hay pending_preview.json; ejecute preview --save-pending")
        data = json.loads(path.read_text(encoding="utf-8"))
        spec = WorkerJobSpec.from_dict(data["spec"])
        if spec.dry_run:
            raise ValueError(
                "El pending preview está en dry_run. Regenera preview con --no-dry-run "
                "o --execute antes de ejecutar."
            )
        return spec
    if args.file:
        return WorkerJobSpec.from_dict(
            json.loads(args.file.read_text(encoding="utf-8"))
        )
    if args.preset and args.company:
        spec = merge_preset_with_company(store.get(args.preset), args.company)
        if spec.dry_run:
            raise ValueError("El preset usa dry_run; pase un JobSpec con dry_run false")
        return spec
    raise ValueError("Indique --pending, --file o --preset con --company")


def _load_spec_for_preset_save(
    args: argparse.Namespace,
    worker_paths: WorkerPaths,
) -> WorkerJobSpec:
    if args.from_pending:
        path = worker_paths.pending_preview_file
        if not path.is_file():
            raise ValueError("No hay pending_preview.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        spec = WorkerJobSpec.from_dict(data["spec"])
    elif args.file:
        spec = WorkerJobSpec.from_dict(
            json.loads(args.file.read_text(encoding="utf-8")),
            require_company=False,
        )
    else:
        raise ValueError("Indique --file o --from-pending")
    data = spec.as_dict()
    data["company"] = ""
    return WorkerJobSpec.from_dict(data, require_company=False)


def _date_filter_from_args(args: argparse.Namespace) -> DateFilterSpec | None:
    if args.date_dynamic:
        return DateFilterSpec(field=args.date_field, dynamic=args.date_dynamic)
    if args.date_from and args.date_to:
        return DateFilterSpec.from_dict(
            {
                "field": args.date_field,
                "from": args.date_from,
                "to": args.date_to,
            }
        )
    if args.date_dynamic is None and not args.date_from:
        return DateFilterSpec(field=args.date_field, dynamic="current_month")
    raise ValueError("Indique --date-dynamic o --date-from y --date-to")


def _date_filter_dict(spec: DateFilterSpec) -> dict[str, Any]:
    data: dict[str, Any] = {"field": spec.field}
    if spec.dynamic:
        data["dynamic"] = spec.dynamic
    else:
        data["from"] = spec.date_from.isoformat() if spec.date_from else None
        data["to"] = spec.date_to.isoformat() if spec.date_to else None
    return data


def _parse_reference_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value.strip()[:10])


if __name__ == "__main__":
    raise SystemExit(main())
