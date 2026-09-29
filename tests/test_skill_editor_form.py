from __future__ import annotations

import json
from pathlib import Path

from agentebc_worker.skill_editor import _form_from_skill
from agentebc_worker.skills import WorkerSkill


def test_form_from_skill_restores_saved_malla_skill() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "worker"
        / "skills"
        / "malla_publicidad_facturar_ventas.skill.json"
    )
    skill = WorkerSkill.from_dict(json.loads(path.read_text(encoding="utf-8")))
    form = _form_from_skill(skill)
    assert form["odata_service"] == "FacturaVenta"
    assert form["document_key_odata"] == "No"
    assert form["date_odata_field"] == "Posting_Date"
    assert "Esperar_Orden_Cliente | No" in str(form["extra_filter_lines"])
    assert "N_x00BA__Contrato" in str(form["report_fields_lines"])
