from agentebc_worker.mailer import SmtpSettings


def test_smtp_from_mail_server_env(monkeypatch) -> None:
    monkeypatch.delenv("AGENTEBC_SMTP_HOST", raising=False)
    monkeypatch.setenv("MAIL_SERVER", "smtp.example.test")
    monkeypatch.setenv("MAIL_PORT", "465")
    monkeypatch.setenv("MAIL_USERNAME", "bot@example.test")
    monkeypatch.setenv("MAIL_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_DEFAULT_SENDER", "bot@example.test")
    monkeypatch.setenv("MAIL_USE_SSL", "true")

    smtp = SmtpSettings.from_environment()

    assert smtp is not None
    assert smtp.host == "smtp.example.test"
    assert smtp.port == 465
    assert smtp.use_ssl is True
    assert smtp.mail_from == "bot@example.test"
