from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.documents import DocumentReader
from agentebc.web_preview import (
    BusinessCentralWebPreview,
    PreviewActionStalledError,
    PreviewError,
    PreviewResult,
    primary_preview_message,
)

from .error_reporting import error_detail_from_exception, error_detail_from_preview

from .job_spec import WorkerJobSpec, uses_custom_odata_service
from .list_documents import document_still_listed_for_job, list_documents_for_job
from .odata_posting import (
    is_registered_for_posting_job,
    posting_action_requires_odata_check,
    registration_check_for_posting_job,
)
from .field_edits import materialize_action_for_job
from .preview import build_job_preview

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentRunOutcome:
    number: str
    outcome: str
    error: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    attempts: int = 1
    error_detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "outcome": self.outcome,
            "error": self.error,
            "fields": dict(self.fields),
            "attempts": self.attempts,
            "error_detail": self.error_detail,
        }


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    preview_summary: str
    dry_run: bool
    outcomes: tuple[DocumentRunOutcome, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "preview_summary": self.preview_summary,
            "dry_run": self.dry_run,
            "outcomes": [item.as_dict() for item in self.outcomes],
        }


def _treat_as_posted_success(
    client: BusinessCentralReadClient,
    definition,
    spec: WorkerJobSpec,
    number: str,
) -> bool:
    return _confirm_removed_from_pending_list(
        client,
        definition,
        spec,
        number,
    )


def _confirm_removed_from_pending_list(
    client: BusinessCentralReadClient,
    definition,
    spec: WorkerJobSpec,
    number: str,
    *,
    pause_seconds: tuple[float, ...] = (0.0, 2.0, 4.0, 8.0),
) -> bool:
    try:
        for wait in pause_seconds:
            if wait:
                time.sleep(wait)
            if is_registered_for_posting_job(
                client,
                definition,
                spec,
                number,
            ):
                return True
    except Exception:
        return False
    return False


def run_job(
    settings: Settings,
    registry: DocumentTypeRegistry,
    spec: WorkerJobSpec,
    *,
    reports_dir: Any = None,
) -> BatchRunResult:
    preview = build_job_preview(
        registry,
        spec,
        client=BusinessCentralReadClient(settings),
    )
    if preview.document_count == 0 and preview.odata_list_error is None:
        return BatchRunResult(
            preview_summary=preview.summary,
            dry_run=spec.dry_run,
            outcomes=(),
        )

    definition = registry.get(spec.type_id)
    action = materialize_action_for_job(definition, spec)
    client = BusinessCentralReadClient(settings)
    listing = list_documents_for_job(client, definition, spec)
    reader = DocumentReader(client)

    outcomes: list[DocumentRunOutcome] = []
    listing_fields = {doc.number: dict(doc.extra_fields) for doc in listing.documents}
    if spec.dry_run:
        for doc in listing.documents:
            outcomes.append(
                DocumentRunOutcome(
                    number=doc.number,
                    outcome="dry_run_skipped",
                    fields=listing_fields.get(doc.number, {}),
                )
            )
        return BatchRunResult(
            preview_summary=preview.summary,
            dry_run=True,
            outcomes=tuple(outcomes),
        )

    preview_engine = BusinessCentralWebPreview(
        settings,
        reports_dir=reports_dir,
    )
    custom_odata = uses_custom_odata_service(spec, definition)
    odata_posting_check = posting_action_requires_odata_check(spec, definition)
    max_attempts = max(1, settings.web_action_max_attempts)

    for doc in listing.documents:
        extra = listing_fields.get(doc.number, {})
        if odata_posting_check and not document_still_listed_for_job(
            client,
            definition,
            spec,
            doc.number,
        ):
            logger.info(
                "Omitiendo %s: ya no está abierta en OData (listado desactualizado).",
                doc.number,
            )
            outcomes.append(
                DocumentRunOutcome(
                    number=doc.number,
                    outcome="skipped",
                    error=(
                        "Omitida: la factura ya no está abierta en OData "
                        "(registrada o fuera del filtro). No se abrió la ficha BC."
                    ),
                    fields=extra,
                )
            )
            continue
        if custom_odata:
            document = doc
        else:
            document = reader.find_document(
                company=spec.company,
                definition=definition,
                number=doc.number,
            )

        attempt = 0
        finished = False
        while attempt < max_attempts and not finished:
            attempt += 1
            try:
                result = preview_engine.run(document, definition, action)
                if result.outcome == "completed" and not result.messages:
                    if odata_posting_check and not _confirm_removed_from_pending_list(
                        client,
                        definition,
                        spec,
                        doc.number,
                    ):
                        raise PreviewActionStalledError(
                            "Registro no completado: "
                            f"{doc.number} sigue abierta en OData "
                            "(no se registró en BC)."
                        )
                    outcomes.append(
                        DocumentRunOutcome(
                            number=doc.number,
                            outcome="success",
                            fields=extra,
                            attempts=attempt,
                        )
                    )
                    finished = True
                    continue
                outcomes.append(
                    _preview_error_outcome(
                        doc.number,
                        extra,
                        result,
                        attempts=attempt,
                    )
                )
                finished = True
                if spec.on_error == "stop":
                    return BatchRunResult(
                        preview_summary=preview.summary,
                        dry_run=False,
                        outcomes=tuple(outcomes),
                    )
            except PreviewActionStalledError as exc:
                if _treat_as_posted_success(client, definition, spec, doc.number):
                    logger.info(
                        "Ficha %s: ya no está en el listado OData; "
                        "se considera registrada.",
                        doc.number,
                    )
                    outcomes.append(
                        DocumentRunOutcome(
                            number=doc.number,
                            outcome="success",
                            fields=extra,
                            attempts=attempt,
                        )
                    )
                    finished = True
                    continue
                logger.warning(
                    "Ficha %s: intento %s/%s sin resultado claro: %s",
                    doc.number,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt >= max_attempts:
                    outcomes.append(
                        DocumentRunOutcome(
                            number=doc.number,
                            outcome="error",
                            error=str(exc),
                            fields=extra,
                            attempts=attempt,
                            error_detail=error_detail_from_exception(str(exc)),
                        )
                    )
                    finished = True
                    if spec.on_error == "stop":
                        return BatchRunResult(
                            preview_summary=preview.summary,
                            dry_run=False,
                            outcomes=tuple(outcomes),
                        )
            except PreviewError as exc:
                message = str(exc)
                if _treat_as_posted_success(client, definition, spec, doc.number):
                    logger.info(
                        "Ficha %s: error web pero ya no en listado (%s); éxito.",
                        doc.number,
                        message,
                    )
                    outcomes.append(
                        DocumentRunOutcome(
                            number=doc.number,
                            outcome="success",
                            fields=extra,
                            attempts=attempt,
                        )
                    )
                    finished = True
                    continue
                outcomes.append(
                    DocumentRunOutcome(
                        number=doc.number,
                        outcome="error",
                        error=message,
                        fields=extra,
                        attempts=attempt,
                        error_detail=error_detail_from_exception(message),
                    )
                )
                finished = True
                if spec.on_error == "stop":
                    return BatchRunResult(
                        preview_summary=preview.summary,
                        dry_run=False,
                        outcomes=tuple(outcomes),
                    )
            except (RuntimeError, ValueError, LookupError) as exc:
                outcomes.append(
                    DocumentRunOutcome(
                        number=doc.number,
                        outcome="error",
                        error=str(exc),
                        fields=extra,
                        attempts=attempt,
                        error_detail=error_detail_from_exception(str(exc)),
                    )
                )
                finished = True
                if spec.on_error == "stop":
                    return BatchRunResult(
                        preview_summary=preview.summary,
                        dry_run=False,
                        outcomes=tuple(outcomes),
                    )

    if odata_posting_check:
        outcomes = _reconcile_outcomes_with_odata(
            client,
            definition,
            spec,
            outcomes,
        )
    return BatchRunResult(
        preview_summary=preview.summary,
        dry_run=False,
        outcomes=tuple(outcomes),
    )


def _reconcile_outcomes_with_odata(
    client: BusinessCentralReadClient,
    definition,
    spec: WorkerJobSpec,
    outcomes: list[DocumentRunOutcome],
) -> list[DocumentRunOutcome]:
    reconciled: list[DocumentRunOutcome] = []
    for item in outcomes:
        registered, after_fields = registration_check_for_posting_job(
            client,
            definition,
            spec,
            item.number,
        )
        merged_fields = dict(item.fields)
        if registered and after_fields:
            merged_fields.update(after_fields)
        if item.outcome == "success":
            if registered:
                reconciled.append(
                    replace(item, fields=merged_fields)
                    if after_fields
                    else item
                )
                continue
            msg = "Comprobación OData: el paso después de acción no confirmó el registro."
            reconciled.append(
                DocumentRunOutcome(
                    number=item.number,
                    outcome="error",
                    error=msg,
                    fields=item.fields,
                    attempts=item.attempts,
                    error_detail=error_detail_from_exception(msg, web_outcome="odata"),
                )
            )
            continue
        if item.outcome == "error" and registered:
            reconciled.append(
                DocumentRunOutcome(
                    number=item.number,
                    outcome="success",
                    error=None,
                    fields=merged_fields,
                    attempts=item.attempts,
                )
            )
            logger.info(
                "Ficha %s: informe error pero OData confirma registro; "
                "se corrige a éxito.",
                item.number,
            )
            continue
        reconciled.append(item)
    return reconciled


def _preview_error_outcome(
    number: str,
    fields: dict[str, str],
    result: PreviewResult,
    *,
    attempts: int,
) -> DocumentRunOutcome:
    if result.messages:
        primary = primary_preview_message(result.messages).description
    elif result.outcome != "completed":
        primary = f"Resultado inesperado de la acción web: {result.outcome}"
    else:
        primary = result.outcome
    return DocumentRunOutcome(
        number=number,
        outcome="error",
        error=primary,
        fields=fields,
        attempts=attempts,
        error_detail=error_detail_from_preview(result),
    )

