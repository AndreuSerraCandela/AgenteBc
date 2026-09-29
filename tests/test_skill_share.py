from __future__ import annotations

import re

from agentebc_worker.skill_share import SkillShareStore, format_share_timestamp
from agentebc_worker.skills import SkillReport, WorkerSkill
from agentebc_worker.job_spec import WorkerJobSpec


def test_format_share_timestamp_utc_to_local() -> None:
    text = format_share_timestamp("2026-09-29T11:37:17.519891+00:00")
    assert re.fullmatch(r"29/09/2026 \d{2}:37", text)


def test_skill_share_roundtrip(tmp_path) -> None:
    store = SkillShareStore(tmp_path / "share")
    skill = WorkerSkill(
        id="demo",
        label="Demo",
        spec=WorkerJobSpec.from_dict(
            {
                "company": "CRONUS",
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
            }
        ),
        report=SkillReport(),
    )
    item = store.share(skill, note="prueba")
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].skill["id"] == "demo"
    store.close(item.id)
    assert store.list_pending() == ()
