from __future__ import annotations

from agentebc_worker.skill_share import SkillShareStore
from agentebc_worker.skills import SkillReport, WorkerSkill
from agentebc_worker.job_spec import WorkerJobSpec


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
