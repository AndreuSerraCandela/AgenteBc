from __future__ import annotations

import re

from agentebc_worker.skill_share import SkillShareStore, format_share_timestamp
from agentebc_worker.skills import SkillReport, WorkerSkill
from agentebc_worker.job_spec import WorkerJobSpec


def test_skills_share_dir_uses_releases_sibling_on_server(
    tmp_path, monkeypatch
) -> None:
    releases = tmp_path / "data" / "releases"
    releases.mkdir(parents=True)
    monkeypatch.delenv("AGENTEBC_WORKER_SKILLS_SHARE_DIR", raising=False)
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))
    monkeypatch.setenv("AGENTEBC_APP_MODE", "portal")

    import agentebc_worker.skill_share as mod

    mod._share_env_loaded = True
    from agentebc_worker.skill_share import skills_share_dir

    assert skills_share_dir() == (tmp_path / "data" / "skills-share").resolve()


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


def test_create_app_loads_share_env_from_env_file(
    tmp_path, monkeypatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "AGENTEBC_SHARE_TOKEN=unit-test-token\n"
        "AGENTEBC_SHARE_URL=https://agentebc.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env))
    monkeypatch.delenv("AGENTEBC_SHARE_TOKEN", raising=False)
    monkeypatch.delenv("AGENTEBC_SHARE_URL", raising=False)

    import agentebc_worker.skill_share as mod

    mod._share_env_loaded = False
    from agentebc_worker.webapp import create_app
    from agentebc_worker.skill_share import share_portal_configured

    create_app()
    assert share_portal_configured() is True
