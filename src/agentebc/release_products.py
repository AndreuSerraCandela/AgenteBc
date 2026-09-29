"""Productos publicables en el portal (Agente desktop, Worker)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ProductId = Literal["agente", "worker"]

_PUBLIC_BASE = "https://agentebc.malla.es/releases"


@dataclass(frozen=True, slots=True)
class ReleaseProduct:
    id: ProductId
    label: str
    manifest_filename: str
    installer_pattern: re.Pattern[str]

    def parse_installer_filename(self, filename: str) -> str | None:
        match = self.installer_pattern.match(filename)
        if not match:
            return None
        return match.group("version")

    def default_download_url(self, filename: str) -> str:
        return f"{_PUBLIC_BASE}/{filename}"


PRODUCTS: dict[ProductId, ReleaseProduct] = {
    "agente": ReleaseProduct(
        id="agente",
        label="AgenteBc",
        manifest_filename="latest.json",
        installer_pattern=re.compile(
            r"^AgenteBc-(?P<version>\d+\.\d+\.\d+)-setup\.exe$",
            re.IGNORECASE,
        ),
    ),
    "worker": ReleaseProduct(
        id="worker",
        label="AgenteBc Worker",
        manifest_filename="worker-latest.json",
        installer_pattern=re.compile(
            r"^AgenteBcWorker-(?P<version>\d+\.\d+\.\d+)-setup\.exe$",
            re.IGNORECASE,
        ),
    ),
}


def normalize_product_id(value: object) -> ProductId:
    token = str(value or "agente").strip().lower()
    if token in PRODUCTS:
        return token  # type: ignore[return-value]
    raise ValueError(f"product no válido: {value!r} (use agente o worker)")
