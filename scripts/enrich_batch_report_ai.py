"""Regenera conclusiones IA por factura (error) en un informe JSON y opcionalmente reenvía correo."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.config import Settings
from agentebc_worker.batch_llm import add_per_invoice_ai_conclusions
from agentebc_worker.batch_report import SkillBatchReport, format_report_plain_text
from agentebc_worker.mailer import SmtpSettings, send_plain_email
from agentebc_worker.skills import SkillStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_json", type=Path, nargs="?")
    parser.add_argument(
        "--mail",
        action="store_true",
        help="Reenviar correo con el informe actualizado",
    )
    parser.add_argument("--to", dest="recipient", default=None)
    args = parser.parse_args()

    path = args.report_json
    if path is None:
        reports = ROOT / "worker" / "reports"
        candidates = sorted(reports.glob("batch-*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print("No hay informes batch en worker/reports", file=sys.stderr)
            return 1
        path = candidates[-1]
        print(f"Usando: {path.name}")

    Settings.load_fresh(ROOT / ".env")
    settings = Settings.from_environment()
    data = json.loads(path.read_text(encoding="utf-8"))
    report = SkillBatchReport.from_dict(data)

    store = SkillStore(
        ROOT / "worker" / "skills",
        bundled_dirs=(ROOT / "config" / "skills",),
    )
    skill = store.get(report.skill_id)

    report, llm_error = add_per_invoice_ai_conclusions(settings, skill, report)
    has_ai = any(
        row.get("ai_conclusion")
        for row in report.rows
        if row.get("outcome") == "error"
    )
    if has_ai:
        report = replace(report, llm_summary=None)
    elif llm_error:
        report = replace(report, llm_summary=f"(Aviso IA: {llm_error})")

    report = replace(report, report_path=str(path.resolve()))
    path.write_text(report.to_json() + "\n", encoding="utf-8")
    print(format_report_plain_text(report))

    if args.mail:
        smtp = SmtpSettings.from_environment()
        if smtp is None:
            print("SMTP no configurado", file=sys.stderr)
            return 1
        recipient = args.recipient or (
            report.notify_emails[0] if report.notify_emails else "andreuserra@malla.es"
        )
        ok = report.totals.get("success", 0)
        err = report.totals.get("error", 0)
        subject = f"[AgenteBc Worker] {report.skill_label} — {ok} OK, {err} error(es)"
        send_plain_email(
            smtp=smtp,
            recipients=(recipient,),
            subject=subject,
            body=format_report_plain_text(report),
        )
        print(f"\nCorreo reenviado a {recipient}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
