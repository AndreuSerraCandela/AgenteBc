from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .call_stack import parse_call_stack_frames
from .license_catalog import ExtensionCatalog
from .microsoft_packages import MicrosoftPackageIndex, resolve_alpackages_path
from .models import (
    DiagnosticReport,
    Evidence,
    Incident,
    ProposedSolution,
    SourceMatch,
)
from .source_index import SourceIndex

if TYPE_CHECKING:
    from .bc_agent_source import BcAgentSourceClient
    from .config import Settings


class DiagnosticService:
    """Construye un expediente verificable sin modificar sistemas externos."""

    def __init__(
        self,
        source_path: Path | None,
        extension_catalog: ExtensionCatalog | None = None,
        *,
        alpackages_path: Path | None = None,
        cache_dir: Path | None = None,
        bc_agent_client: BcAgentSourceClient | None = None,
    ) -> None:
        allowed_roots: tuple[Path, ...] | None = None
        self._catalog = extension_catalog
        if source_path and extension_catalog and extension_catalog.is_enabled:
            allowed_roots = extension_catalog.allowed_roots()
        self._source_index = (
            SourceIndex(source_path, allowed_roots=allowed_roots)
            if source_path
            else None
        )
        resolved_alpackages = resolve_alpackages_path(source_path, alpackages_path)
        self._microsoft_index: MicrosoftPackageIndex | None = None
        if resolved_alpackages is not None:
            try:
                self._microsoft_index = MicrosoftPackageIndex(
                    resolved_alpackages,
                    cache_dir=cache_dir,
                )
            except ValueError:
                self._microsoft_index = None
        self._bc_agent_client = bc_agent_client

    def diagnose(self, incident: Incident) -> DiagnosticReport:
        error = incident.error_text.strip()
        if not error:
            raise ValueError("El texto del error no puede estar vacío")

        stack_matches = ()
        microsoft_matches = ()
        subscriber_matches = ()
        text_matches = ()
        stack_frames = (
            parse_call_stack_frames(incident.call_stack)
            if incident.call_stack
            else ()
        )
        if self._source_index is not None and incident.call_stack:
            stack_matches = tuple(
                self._source_index.search_call_stack(incident.call_stack)
            )
        if (
            incident.call_stack
            and not stack_matches
            and self._microsoft_index is not None
        ):
            microsoft_matches = tuple(
                self._microsoft_index.search_call_stack(incident.call_stack)
            )
        if (
            self._source_index is not None
            and incident.call_stack
            and not stack_matches
            and not microsoft_matches
            and stack_frames
        ):
            subscriber_matches = tuple(
                self._source_index.search_event_subscribers(stack_frames[0])
            )
        if (
            self._source_index is not None
            and not stack_matches
            and not microsoft_matches
            and not subscriber_matches
        ):
            text_matches = tuple(self._source_index.search(error))
        matches = (
            stack_matches
            or microsoft_matches
            or subscriber_matches
            or text_matches
        )
        remote_matches = ()
        if not matches and self._bc_agent_client is not None:
            remote_matches = self._search_remote(incident, error)
            matches = remote_matches
        remote_from_microsoft = any(".app!" in match.path for match in remote_matches)
        matched_by_stack = bool(
            stack_matches or microsoft_matches or remote_matches
        )
        matched_by_subscriber = bool(subscriber_matches) and not matched_by_stack
        matched_by_microsoft = bool(
            microsoft_matches or (remote_matches and remote_from_microsoft)
        ) and not bool(stack_matches)
        evidence = [
            Evidence(
                kind="error",
                description="Mensaje observado durante el intento de registro",
                value=error,
            )
        ]
        if incident.call_stack:
            evidence.append(
                Evidence(
                    kind="call_stack",
                    description="Pila de llamadas aportada",
                    value=incident.call_stack,
                )
            )
        if incident.document_number:
            evidence.append(
                Evidence(
                    kind="document",
                    description="Documento afectado",
                    value=incident.document_number,
                )
            )

        if matches and matched_by_stack:
            best = matches[0]
            origin = (
                "la aplicación base Microsoft"
                if matched_by_microsoft
                else "el código"
            )
            summary = (
                f"La pila de llamadas apunta a {best.path}:{best.line} en "
                f"{origin}. Revise la condición y los datos leídos en ese punto."
            )
            confidence = "alta"
            proposals = (
                ProposedSolution(
                    description=(
                        "Inspeccionar el procedimiento señalado por la pila de "
                        "llamadas y la condición que dispara el error."
                    ),
                    verification=(
                        "Contrastar los campos implicados con el documento "
                        "afectado y con un caso equivalente que funcione."
                    ),
                ),
            )
        elif matches and matched_by_subscriber:
            top = stack_frames[0]
            summary = (
                f"La pila apunta a {top.object_name} ({top.object_type} "
                f"{top.object_id}), objeto de la aplicación base sin fuentes "
                "locales. Se listan suscriptores de evento en extensiones propias."
            )
            confidence = "media"
            proposals = (
                ProposedSolution(
                    description=(
                        "Revisar si algún suscriptor de evento modifica el flujo "
                        f"de {top.object_name} antes del punto señalado por la pila."
                    ),
                    verification=(
                        "Comparar el comportamiento con y sin la extensión, y "
                        "validar los datos del documento afectado."
                    ),
                ),
            )
        elif stack_frames and not matches:
            top = stack_frames[0]
            summary = (
                f"La pila apunta a {top.object_name} ({top.object_type} "
                f"{top.object_id}), procedimiento {top.procedure}, pero ese objeto "
                "no está en las fuentes locales (probablemente aplicación base "
                "Microsoft)."
            )
            confidence = "media"
            proposals = (
                ProposedSolution(
                    description=(
                        "Consultar la documentación o símbolos de la aplicación "
                        "base para ese procedimiento y revisar la configuración "
                        "relacionada con el mensaje."
                    ),
                    verification=(
                        "Contrastar los campos indicados en el mensaje con la "
                        "configuración y el documento afectado."
                    ),
                ),
            )
        elif matches:
            summary = (
                f"Se han localizado {len(matches)} candidatos en el código. "
                "Una coincidencia indica dónde se genera o referencia el mensaje, "
                "pero todavía no demuestra por sí sola la causa raíz."
            )
            confidence = "media"
            proposals = (
                ProposedSolution(
                    description=(
                        "Revisar la condición y los datos leídos alrededor de la "
                        "coincidencia mejor puntuada."
                    ),
                    verification=(
                        "Comparar esos campos con el documento afectado y con un "
                        "documento equivalente que registre correctamente."
                    ),
                ),
            )
        else:
            summary = (
                "No se ha localizado el mensaje en las fuentes disponibles. "
                "Puede proceder de la aplicación base, una dependencia, un mensaje "
                "construido dinámicamente o una versión distinta del código."
            )
            confidence = "baja"
            proposals = (
                ProposedSolution(
                    description=(
                        "Obtener la pila de llamadas y confirmar la versión exacta "
                        "de las extensiones instaladas."
                    ),
                    verification=(
                        "Repetir el análisis con símbolos y fuentes que coincidan "
                        "con el entorno donde ocurrió el error."
                    ),
                ),
            )

        limitations = [
            "El informe de diagnóstico no escribe en SQL.",
            "La automatización web puede haber modificado datos en Business Central "
            "si la acción reproducida lo requiere.",
            "Las coincidencias de código son candidatos y requieren validación.",
        ]
        if self._source_index is None and self._bc_agent_client is None:
            limitations.append("No se configuró un directorio de código fuente.")
        if self._bc_agent_client is not None and self._source_index is None:
            limitations.append(
                "El código se consulta de forma remota mediante objetos-bc-agent."
            )
        if self._microsoft_index is None and self._bc_agent_client is None:
            limitations.append(
                "No se indexaron paquetes Microsoft (.alpackages); los errores "
                "del estándar dependerán de suscriptores o búsqueda textual."
            )
        if self._catalog and self._catalog.is_enabled:
            roots = self._catalog.allowed_roots()
            if roots:
                limitations.append(
                    f"Solo se buscan extensiones licenciadas para "
                    f"{self._catalog.license_client} ({len(roots)} carpetas)."
                )
            elif self._catalog.limitation:
                limitations.append(self._catalog.limitation)
        if not incident.call_stack:
            limitations.append("No se aportó una pila de llamadas.")

        return DiagnosticReport(
            incident=incident,
            summary=summary,
            confidence=confidence,
            evidence=tuple(evidence),
            source_matches=matches,
            proposed_solutions=proposals,
            limitations=tuple(limitations),
        )

    def _search_remote(
        self,
        incident: Incident,
        error: str,
    ) -> tuple[SourceMatch, ...]:
        if self._bc_agent_client is None:
            return ()
        if incident.call_stack:
            return self._bc_agent_client.search_call_stack(incident.call_stack)
        return self._bc_agent_client.search_text(error)


def build_diagnostic_service(
    settings: Settings,
    extension_catalog: ExtensionCatalog | None = None,
    *,
    cache_dir: Path | None = None,
) -> DiagnosticService:
    from .bc_agent_source import BcAgentSourceClient

    bc_agent_client = None
    if settings.bc_agent_url and settings.bc_agent_token:
        bc_agent_client = BcAgentSourceClient(
            settings.bc_agent_url,
            settings.bc_agent_token,
            timeout_seconds=settings.request_timeout_seconds,
        )
    return DiagnosticService(
        settings.source_path,
        extension_catalog,
        alpackages_path=settings.alpackages_path,
        cache_dir=cache_dir,
        bc_agent_client=bc_agent_client,
    )
