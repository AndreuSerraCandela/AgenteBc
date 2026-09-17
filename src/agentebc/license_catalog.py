from __future__ import annotations

import json
import re
from pathlib import Path

import requests

DEFAULT_LICENSE_URL = "https://license.malla.es"


class LicenseCatalogError(RuntimeError):
    pass


class ExtensionCatalog:
    """Resuelve qué carpetas de fuentes pertenecen a un cliente de license.malla.es."""

    def __init__(
        self,
        source_root: Path,
        *,
        license_url: str | None = None,
        license_token: str | None = None,
        license_client: str | None = None,
        request_timeout_seconds: float = 15.0,
    ) -> None:
        self.source_root = source_root.resolve()
        self.license_url = (license_url or DEFAULT_LICENSE_URL).rstrip("/")
        self.license_token = (license_token or "").strip() or None
        self.license_client = (license_client or "").strip() or None
        self.request_timeout_seconds = request_timeout_seconds
        self._allowed_roots: tuple[Path, ...] | None = None
        self.limitation: str | None = None

    @property
    def is_enabled(self) -> bool:
        return bool(self.license_client)

    def allowed_roots(self) -> tuple[Path, ...]:
        if self._allowed_roots is not None:
            return self._allowed_roots
        if not self.license_client:
            self._allowed_roots = ()
            return self._allowed_roots
        if not self.license_token:
            self.limitation = (
                "No se configuró AGENTEBC_LICENSE_TOKEN; no se pueden filtrar "
                "las extensiones licenciadas de Malla."
            )
            self._allowed_roots = ()
            return self._allowed_roots
        try:
            names = self._fetch_licensed_extension_names()
            self._allowed_roots = resolve_extension_roots(
                self.source_root,
                names,
            )
            if not self._allowed_roots:
                self.limitation = (
                    f"No se localizaron carpetas de fuentes para las extensiones "
                    f"licenciadas de {self.license_client}."
                )
        except (LicenseCatalogError, requests.RequestException) as exc:
            self.limitation = (
                f"No se pudo consultar license.malla.es para {self.license_client}: {exc}"
            )
            self._allowed_roots = ()
        return self._allowed_roots

    def _fetch_licensed_extension_names(self) -> tuple[str, ...]:
        response = requests.get(
            f"{self.license_url}/api/v1/admin/customers",
            headers={"X-MyBeLic-Token": self.license_token or ""},
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise LicenseCatalogError("Respuesta inesperada de license.malla.es")

        customer = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("name") == self.license_client
            ),
            None,
        )
        if customer is None:
            raise LicenseCatalogError(
                f"Cliente de licencia no encontrado: {self.license_client}"
            )

        names: list[str] = []
        for application in customer.get("applications", []):
            if not isinstance(application, dict):
                continue
            if application.get("blocked"):
                continue
            if application.get("application_type") != "Business Central":
                continue
            extension = application.get("extension") or {}
            if not isinstance(extension, dict):
                continue
            name = str(extension.get("name", "")).strip()
            if name:
                names.append(name)
        if not names:
            raise LicenseCatalogError(
                f"El cliente {self.license_client} no tiene extensiones BC activas"
            )
        return tuple(names)


def normalize_extension_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def discover_extension_roots(source_root: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not source_root.is_dir():
        return mapping

    for child in source_root.iterdir():
        if not child.is_dir():
            continue
        manifest = _find_manifest(child)
        if manifest is None:
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        app_name = str(data.get("name", "")).strip()
        if app_name:
            mapping[normalize_extension_key(app_name)] = child
        mapping[normalize_extension_key(child.name)] = child
    return mapping


def resolve_extension_roots(
    source_root: Path,
    extension_names: tuple[str, ...],
) -> tuple[Path, ...]:
    discovered = discover_extension_roots(source_root)
    roots: list[Path] = []
    seen: set[Path] = set()
    for name in extension_names:
        root = discovered.get(normalize_extension_key(name))
        if root is None or root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return tuple(roots)


def _find_manifest(extension_root: Path) -> Path | None:
    for manifest_name in ("app.json", "aapp.json"):
        manifest = extension_root / manifest_name
        if manifest.is_file():
            return manifest
    return None
