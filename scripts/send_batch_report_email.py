"""Envía por correo un informe batch JSON ya generado."""
from __future__ import annotations

import json
import sys
from dataclasses import replace  # noqa: F401 — used when notify_emails empty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.config import Settings
from agentebc_worker.batch_report import SkillBatchReport, format_report_plain_text
from agentebc_worker.mailer import SmtpSettings, send_plain_email


def main() -> int:
    if len(sys.argv) < 2:
        reports = ROOT / "worker" / "reports"
        candidates = sorted(reports.glob("batch-*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print("Uso: send_batch_report_email.py <informe.json> [destino@email]", file=sys.stderr)
            return 1
        path = candidates[-1]
        print(f"Usando último informe: {path.name}")
    else:
        path = Path(sys.argv[1])
    recipient = sys.argv[2] if len(sys.argv) > 2 else "andreuserra@malla.es"

    Settings.load_fresh(ROOT / ".env")
    smtp = SmtpSettings.from_environment()
    if smtp is None:
        print("SMTP no configurado (MAIL_* / AGENTEBC_SMTP_*)", file=sys.stderr)
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    report = SkillBatchReport.from_dict(data)
    if not report.notify_emails:
        report = replace(report, notify_emails=(recipient,))
    ok = report.totals.get("success", 0)
    err = report.totals.get("error", 0)
    subject = f"[AgenteBc Worker] {report.skill_label} — {ok} OK, {err} error(es)"
    body = format_report_plain_text(report)
    send_plain_email(
        smtp=smtp,
        recipients=(recipient,),
        subject=subject,
        body=body,
    )
    print(f"Enviado a {recipient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
