"""Ejecuta un lote pequeño, reconcilia OData y envía informe por correo (skill)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.bc_client import BusinessCentralReadClient
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.odata_posting import is_registered_for_posting_job
from agentebc_worker.paths import WorkerPaths
from agentebc_worker.batch_report import format_report_plain_text
from agentebc_worker.runner import run_job
from agentebc_worker.skill_postrun import finalize_skill_batch
from agentebc_worker.skills import WorkerSkill


def main() -> int:
    argv = [a for a in sys.argv[1:] if a.startswith("-")]
    pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    send_mail = "--no-mail" not in argv
    limit = int(pos[0]) if pos else 2
    skill_path = ROOT / "worker/skills/malla_publicidad_facturar_ventas.skill.json"
    worker_skill = WorkerSkill.from_dict(
        json.loads(skill_path.read_text(encoding="utf-8"))
    )
    if len(pos) > 1:
        job_path = Path(pos[1])
        spec_data = json.loads(job_path.read_text(encoding="utf-8"))
        if len(sys.argv) > 1:
            spec_data["limit"] = limit
    else:
        spec_data = {**worker_skill.spec.as_dict(), "limit": limit}
    spec_data["dry_run"] = False
    spec_data["on_error"] = "report_and_continue"
    spec = WorkerJobSpec.from_dict(spec_data)
    settings = Settings.from_environment()
    registry = DocumentTypeRegistry(ROOT / "config/document_types.json")
    spec.validate_against_registry(registry)
    worker_paths = WorkerPaths.resolve()
    result = run_job(
        settings,
        registry,
        spec,
        reports_dir=worker_paths.app.reports_dir,
    )
    client = BusinessCentralReadClient(settings)
    definition = registry.get(spec.type_id)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    print("\n--- Verificación OData ---")
    exit_code = 0
    for item in result.outcomes:
        registered = is_registered_for_posting_job(
            client,
            definition,
            spec,
            item.number,
        )
        state = "registrada" if registered else "PENDIENTE (Open)"
        ok = (item.outcome == "success") == registered
        if not ok:
            exit_code = 1
        print(
            f"{item.number}: informe={item.outcome} odata={state} "
            f"coherente={'sí' if ok else 'NO'}"
        )
        if item.error:
            print(f"  error: {item.error}")
    batch_report = finalize_skill_batch(
        settings,
        worker_skill,
        result,
        reports_dir=worker_paths.batch_reports_dir,
        send_email=send_mail,
        run_llm=False,
    )
    print("\n--- Informe lote (texto) ---")
    print(format_report_plain_text(batch_report))
    print(f"\nInforme JSON: {batch_report.report_path}")
    if batch_report.email_status:
        print(f"Correo: {batch_report.email_status}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
