from __future__ import annotations

from dataclasses import replace

from agentebc.config import Settings
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.field_edits import spec_with_posting_date_mode
from agentebc_worker.skill_connection import (
    SkillConnection,
    resolve_skill_company,
    settings_for_skill,
)
from agentebc_worker.simple_portal import _posting_field_label
from agentebc_worker.skills import SkillReport, WorkerSkill


def _skill(*, company: str = "", conn_company: str = "") -> WorkerSkill:
    connection = None
    if conn_company:
        connection = SkillConnection(company=conn_company)
    return WorkerSkill(
        id="t",
        label="T",
        spec=WorkerJobSpec.from_dict(
            {
                "company": company,
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
            },
            require_company=False,
        ),
        report=SkillReport(),
        connection=connection,
    )


def test_resolve_skill_company_override() -> None:
    skill = _skill(company="A")
    assert resolve_skill_company(skill, override="B") == "B"


def test_portal_posting_date_mode_today() -> None:
    skill = _skill(company="A")
    spec = spec_with_posting_date_mode(skill.to_job_spec(dry_run=True), "today")
    assert spec.before_action_field_edits[0].value == "today"


def test_posting_field_label_from_skill() -> None:
    skill = WorkerSkill.from_dict(
        {
            "id": "t",
            "label": "T",
            "spec": {
                "company": "A",
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
                "before_action_field_edits": [
                    {"field_label": "Fecha registro", "value": "today"}
                ],
            },
        }
    )
    assert _posting_field_label(skill) == "Fecha registro"


def test_resolve_skill_company_from_connection() -> None:
    skill = _skill(conn_company="Malla Publicidad")
    assert resolve_skill_company(skill) == "Malla Publicidad"


def test_settings_for_skill_overlays_urls() -> None:
    base = Settings(
        odata_base_url="http://old/ODataV4",
        web_base_url=None,
        auth_mode="windows",
        username=None,
        password=None,
        company=None,
        license_token=None,
        license_url=None,
        license_client=None,
        source_path=None,
        alpackages_path=None,
        sql_connection_string=None,
        tls_verify=True,
        request_timeout_seconds=30.0,
        web_action_idle_timeout_seconds=60.0,
        web_action_max_attempts=3,
        browser_headless=False,
        browser_channel=None,
        ai_provider=None,
        worker_ai_provider=None,
        lm_studio_url=None,
        lm_studio_model=None,
        worker_lm_studio_url=None,
        worker_lm_studio_model=None,
        deepseek_api_key=None,
        deepseek_model=None,
        deepseek_url=None,
        deepseek_web_url=None,
        deepseek_web_profile=None,
        deepseek_web_timeout_seconds=90.0,
        deepseek_web_login_timeout_seconds=120.0,
        deepseek_web_cdp_url=None,
        ai_web_cdp_url=None,
        google_ai_web_url=None,
        bc_agent_url=None,
        bc_agent_token=None,
        share_url=None,
        share_token=None,
        share_user=None,
        web_company_use_guid=False,
        web_use_windows_session=True,
        web_browser_profile=None,
    )
    skill = _skill()
    skill = replace(
        skill,
        connection=SkillConnection(
            odata_base_url="http://bc/ODataV4",
            web_base_url="http://bc/web",
        ),
    )
    merged = settings_for_skill(base, skill)
    assert merged.odata_base_url == "http://bc/ODataV4"
    assert merged.web_base_url == "http://bc/web"
