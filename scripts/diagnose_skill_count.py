"""Diagnóstico: por qué el skill devuelve 0 documentos."""
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
from agentebc.documents import bc_urlencode
from agentebc_worker.job_spec import (
    odata_date_field,
    resolve_date_filter,
    resolve_odata_key_field,
    resolve_odata_service,
)
from agentebc_worker.list_documents import list_documents_for_job, _row_still_open_for_posting
from agentebc_worker.paths import WorkerPaths
from agentebc_worker.preview import build_job_preview
from agentebc_worker.skills import SkillStore


def main() -> int:
    Settings.load_fresh(ROOT / ".env")
    paths = WorkerPaths.resolve()
    store = SkillStore(paths.user_skills_dir, bundled_dirs=paths.bundled_skills_dirs)
    skill = store.get("malla_publicidad_facturar_ventas")
    spec = skill.to_job_spec(dry_run=True)
    registry = DocumentTypeRegistry(ROOT / "config/document_types.json")
    definition = registry.get(spec.type_id)
    client = BusinessCentralReadClient(Settings.from_environment())
    ref = date.today()

    print("Skill cargado desde:", paths.user_skills_dir / f"{skill.id}.skill.json")
    print("Filtros OData extra:", spec.extra_odata_filters)
    print("Fecha:", spec.date_filter)
    print("Servicio:", spec.odata_service or definition.odata_service)

    service = resolve_odata_service(spec, definition)
    key_field = resolve_odata_key_field(spec, definition)
    filters: list[str] = []
    for field, value in spec.extra_odata_filters.items():
        if isinstance(value, bool):
            filters.append(f"{field} eq {str(value).lower()}")
        elif value == "":
            filters.append(f"{field} eq ''")
        else:
            filters.append(f"{field} eq '{value}'")
    odata_f = odata_date_field(definition, spec.date_filter, custom_odata_service=True)
    dfrom, dto = resolve_date_filter(spec.date_filter, reference=ref)
    filters.append(f"{odata_f} ge {dfrom.isoformat()}")
    filters.append(f"{odata_f} le {dto.isoformat()}")

    query = bc_urlencode(
        {
            "company": spec.company,
            "$filter": " and ".join(filters),
            "$select": f"{key_field},Status,Posting_Date,{odata_f}",
            "$top": "500",
        }
    )
    endpoint = f"{service}?{query}"
    print("\nConsulta OData (sin filtro Open en Python):")
    print(endpoint[:200], "...")

    data = client.get(endpoint)
    rows = data.get("value", []) if isinstance(data, dict) else []
    print(f"\nFilas OData: {len(rows)}")
    open_rows = [r for r in rows if isinstance(r, dict) and _row_still_open_for_posting(r)]
    print(f"Tras filtro Status Open (Python): {len(open_rows)}")
    if rows:
        sample = rows[0]
        print("Ejemplo Status:", sample.get("Status"), "Posting_Date:", sample.get("Posting_Date"))

    select = ",".join(
        sorted(
            {
                key_field,
                odata_f,
                "Status",
                "Esperar_Orden_Cliente",
                "Estado_Contrato",
                "N_x00BA__Contrato",
            }
        )
    )
    q2 = bc_urlencode(
        {
            "company": spec.company,
            "$filter": " and ".join(filters),
            "$select": select,
            "$top": str(spec.limit + 1),
            "$orderby": f"{key_field} asc",
        }
    )
    data2 = client.get(f"{service}?{q2}")
    rows2 = data2.get("value", []) if isinstance(data2, dict) else []
    print(f"\nCon mismo \$select que list_documents: {len(rows2)} filas")
    if rows2:
        r0 = rows2[0]
        print(
            "  1ª fila:",
            r0.get(key_field),
            "Status=",
            repr(r0.get("Status")),
            "open=",
            _row_still_open_for_posting(r0),
        )

    listed = list_documents_for_job(client, definition, spec, reference_date=ref)
    preview = build_job_preview(registry, spec, client=client, reference_date=ref)
    print(f"\nlist_documents_for_job: {len(listed.documents)}")
    print(f"Preview document_count: {preview.document_count}")
    print(preview.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
