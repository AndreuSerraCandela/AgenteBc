"""Comprueba vía OData si números siguen en el listado pendiente del skill."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.odata_posting import is_registered_for_posting_job


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill",
        type=Path,
        default=Path("worker/skills/malla_publicidad_facturar_ventas.skill.json"),
    )
    parser.add_argument(
        "--numbers",
        nargs="*",
        help="Números a comprobar (si falta, usa --batch-report)",
    )
    parser.add_argument(
        "--batch-report",
        type=Path,
        help="JSON de informe batch (toma todos los number de rows)",
    )
    args = parser.parse_args()

    skill = json.loads(args.skill.read_text(encoding="utf-8"))
    spec = WorkerJobSpec.from_dict(skill["spec"])
    registry = DocumentTypeRegistry(Path("config/document_types.json"))
    definition = registry.get(spec.type_id)
    client = BusinessCentralReadClient(Settings.from_environment())

    numbers: list[str] = list(args.numbers or [])
    if args.batch_report:
        report = json.loads(args.batch_report.read_text(encoding="utf-8"))
        numbers.extend(row["number"] for row in report.get("rows", []))

    if not numbers:
        print("Indique --numbers o --batch-report", file=sys.stderr)
        return 2

    pending: list[str] = []
    done: list[str] = []
    for number in numbers:
        if is_registered_for_posting_job(client, definition, spec, number):
            done.append(number)
        else:
            pending.append(number)

    print(f"Comprobados: {len(numbers)}")
    print(f"Registradas (fuera del listado OData): {len(done)}")
    print(f"Pendientes (siguen en listado): {len(pending)}")
    if pending:
        print("Pendientes:", ", ".join(pending))
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
