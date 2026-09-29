"""Valida .env para el worker (invocado desde setup-worker-test-env.ps1)."""
from __future__ import annotations

import sys

from agentebc.config import ConfigurationError, Settings
from agentebc_worker.worker_ai import resolve_worker_ai_provider, worker_ai_enabled


def main() -> int:
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        print(f"Configuracion invalida: {exc}", file=sys.stderr)
        return 1
    print("  OData:", settings.odata_base_url)
    print("  Web Playwright:", settings.resolve_web_client_base_url())
    print("  Empresa:", settings.company)
    print("  Auth:", settings.auth_mode)
    worker_provider = resolve_worker_ai_provider(settings)
    print("  IA consultor:", settings.ai_provider or "(sin configurar)")
    print("  IA worker (informes):", worker_provider or "(sin configurar)")
    if worker_ai_enabled(settings):
        url = settings.worker_lm_studio_url or settings.lm_studio_url
        model = settings.worker_lm_studio_model or settings.lm_studio_model
        print("  LM Studio worker:", url)
        if model:
            print("  Modelo worker:", model)
    else:
        print(
            "  AVISO: resumen IA del informe desactivado hasta configurar "
            "AGENTEBC_WORKER_AI_PROVIDER=lm_studio y "
            "AGENTEBC_WORKER_LM_STUDIO_URL"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
