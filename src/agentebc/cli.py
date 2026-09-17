from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from .bc_client import BusinessCentralReadClient
from .config import ConfigurationError, Settings
from .diagnosis import build_diagnostic_service
from .license_catalog import ExtensionCatalog
from .models import Incident
from .source_index import SourceIndex


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentebc",
        description="Diagnóstico en modo lectura para Business Central",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "check-config",
        help="Valida y muestra la configuración sin revelar secretos",
    )

    test_bc = subcommands.add_parser(
        "test-bc",
        help="Ejecuta un GET de prueba contra OData/API",
    )
    test_bc.add_argument("--endpoint", required=True)

    search = subcommands.add_parser(
        "search-code",
        help="Busca un texto en fuentes AL/C-AL",
    )
    search.add_argument("--text", required=True)
    search.add_argument("--limit", type=int, default=10)

    diagnose = subcommands.add_parser(
        "diagnose",
        help="Genera un expediente diagnóstico JSON",
    )
    diagnose.add_argument("--error", required=True)
    diagnose.add_argument("--document")
    diagnose.add_argument("--company")
    diagnose.add_argument("--user")
    diagnose.add_argument("--call-stack")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_environment()
        result = _run(args, settings)
    except (ConfigurationError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _run(args: argparse.Namespace, settings: Settings) -> Any:
    if args.command == "check-config":
        return settings.safe_summary()

    if args.command == "test-bc":
        client = BusinessCentralReadClient(settings)
        data = client.get(args.endpoint)
        return {"ok": True, "response": data}

    if args.command == "search-code":
        if settings.source_path is None:
            raise ConfigurationError("Falta AGENTEBC_SOURCE_PATH")
        catalog = _extension_catalog(settings)
        allowed_roots = catalog.allowed_roots() if catalog else None
        matches = SourceIndex(
            settings.source_path,
            allowed_roots=allowed_roots,
        ).search(
            args.text,
            limit=args.limit,
        )
        return [asdict(match) for match in matches]

    if args.command == "diagnose":
        incident = Incident(
            error_text=args.error,
            document_number=args.document,
            company=args.company,
            user=args.user,
            call_stack=args.call_stack,
        )
        report = build_diagnostic_service(
            settings,
            _extension_catalog(settings),
        ).diagnose(incident)
        return report.as_dict()

    raise ValueError(f"Comando desconocido: {args.command}")


def _extension_catalog(settings: Settings) -> ExtensionCatalog | None:
    if settings.source_path is None or not settings.license_client:
        return None
    return ExtensionCatalog(
        settings.source_path,
        license_url=settings.license_url,
        license_token=settings.license_token,
        license_client=settings.license_client,
        request_timeout_seconds=settings.request_timeout_seconds,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
