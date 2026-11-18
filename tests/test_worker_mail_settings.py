from pathlib import Path

from agentebc_worker.batch_llm import _conclude_single_row
from agentebc_worker.mail_settings import mail_form_from_env, save_worker_mail_settings
from agentebc_worker.mailer import SmtpSettings
from agentebc_worker.skills import SkillReport, WorkerSkill
from agentebc_worker.job_spec import WorkerJobSpec


def test_save_mail_settings_reloads_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AGENTEBC_AUTH_MODE=windows\n", encoding="utf-8")
    monkeypatch.delenv("AGENTEBC_SMTP_HOST", raising=False)
    monkeypatch.delenv("MAIL_SERVER", raising=False)
    monkeypatch.delenv("AGENTEBC_SMTP_FROM", raising=False)
    monkeypatch.delenv("MAIL_DEFAULT_SENDER", raising=False)
    monkeypatch.delenv("MAIL_USE_SSL", raising=False)

    save_worker_mail_settings(
        env_file,
        {
            "host": "smtp.example.test",
            "port": "465",
            "user": "bot@example.test",
            "sender": "bot@example.test",
            "security": "ssl",
            "password": "secret",
        },
    )

    smtp = SmtpSettings.from_environment()
    assert smtp is not None
    assert smtp.host == "smtp.example.test"
    assert smtp.port == 465
    assert smtp.use_ssl is True
    assert smtp.mail_from == "bot@example.test"
    form = mail_form_from_env(env_file)
    assert form["password_set"] == "1"
    assert form["host"] == "smtp.example.test"


def test_blank_password_keeps_previous(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    save_worker_mail_settings(
        env_file,
        {
            "host": "smtp.example.test",
            "port": "587",
            "user": "bot@example.test",
            "sender": "bot@example.test",
            "security": "tls",
            "password": "secret",
        },
    )
    save_worker_mail_settings(
        env_file,
        {
            "host": "smtp.example.test",
            "port": "587",
            "user": "bot@example.test",
            "sender": "bot@example.test",
            "security": "tls",
            "password": "",
        },
    )
    assert "AGENTEBC_SMTP_PASSWORD=secret" in env_file.read_text(encoding="utf-8")


def test_ai_conclusion_receives_settings(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _enrich(message, *, company, settings):
        seen["settings"] = settings
        seen["company"] = company
        return ()

    monkeypatch.setattr(
        "agentebc_worker.batch_llm.enrich_diagnostic_evidence",
        _enrich,
    )
    skill = WorkerSkill(
        id="t",
        label="T",
        spec=WorkerJobSpec.from_dict(
            {
                "company": "Malla Publicidad",
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
            }
        ),
        report=SkillReport(),
    )

    class _Client:
        def complete(self, user_prompt: str, system_prompt: str) -> str:
            return "conclusión"

    class _Diagnosis:
        def diagnose(self, incident):
            raise RuntimeError("sin fuentes")

    marker = object()
    text = _conclude_single_row(
        _Client(),
        settings=marker,
        diagnostic_service=_Diagnosis(),
        skill=skill,
        case_label="caso",
        row={"number": "ML1", "error": "fallo"},
    )
    assert text == "conclusión"
    assert seen["settings"] is marker
    assert seen["company"] == "Malla Publicidad"
