from __future__ import annotations

import threading
from dataclasses import asdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from . import __version__
from .bc_client import BusinessCentralReadClient
from .config import ConfigurationError, Settings
from .env_store import (
    apply_env_updates,
    collect_setup_updates,
    is_setup_complete,
    mask_secret_values,
    read_env_values,
)
from .paths import AppPaths, is_desktop_mode
from .diagnosis import build_diagnostic_service
from .license_catalog import ExtensionCatalog
from .document_types import (
    ActionDefinition,
    DocumentTypeDefinition,
    DocumentTypeRegistry,
    RUNNABLE_SAFETY_LEVELS,
    format_dialog_steps_text,
    format_field_edits_text,
    parse_field_edits_text,
    parse_dialog_steps_text,
)
from .documents import DocumentNotFoundError, DocumentReference, DocumentReader
from .evidence_enrichment import EvidenceItem, enrich_from_message
from .deepseek_web import DeepSeekWebError
from .google_ai_web import GoogleAiWebError
from .llm_conclusions import _WEB_AI_PROVIDERS, build_llm_client, request_ai_conclusion
from .models import DiagnosticReport, Evidence, Incident, ProposedSolution, SourceMatch
from .sql_reader import SqlReadOnlyClient
from .web_preview import (
    BusinessCentralActionExplorer,
    BusinessCentralWebPreview,
    PreviewError,
    PreviewMessage,
    primary_preview_message,
)

_preview_lock = threading.Lock()


def create_app(
    settings: Settings | None = None,
    *,
    app_paths: AppPaths | None = None,
) -> Flask:
    package_dir = Path(__file__).resolve().parent
    paths = app_paths or AppPaths.resolve()
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    app.config["TEMPLATES_AUTO_RELOAD"] = not is_desktop_mode()
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    settings_state = {"current": settings or Settings.from_environment()}

    def current_settings() -> Settings:
        return settings_state["current"]

    def reload_settings() -> Settings:
        settings_state["current"] = Settings.load_fresh(paths.env_file)
        return settings_state["current"]

    reports_dir = paths.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    registry = DocumentTypeRegistry(paths.document_types_file)

    def document_reader() -> DocumentReader:
        return DocumentReader(BusinessCentralReadClient(current_settings()))

    def load_companies(fallback: str | None = None) -> list[str]:
        try:
            return document_reader().list_companies()
        except Exception:
            return [fallback] if fallback else []

    @app.get("/api/app-info")
    def app_info():
        return jsonify(
            {
                "name": "AgenteBc",
                "version": __version__,
                **paths.summary(),
            }
        )

    def setup_form_values() -> dict[str, str]:
        return mask_secret_values(read_env_values(paths.env_file))

    @app.get("/setup")
    def app_setup():
        setup_complete = is_setup_complete(current_settings())
        return render_template(
            "setup.html",
            values=setup_form_values(),
            env_file=str(paths.env_file),
            setup_complete=setup_complete,
            saved=request.args.get("saved"),
            error=request.args.get("error"),
            test_ok=request.args.get("test_ok"),
        )

    @app.post("/setup")
    def app_setup_save():
        updates = collect_setup_updates(request.form)
        action = request.form.get("action", "save")
        try:
            apply_env_updates(paths.env_file, updates)
            reload_settings()
        except (ConfigurationError, ValueError) as exc:
            return render_template(
                "setup.html",
                values={**setup_form_values(), **updates},
                env_file=str(paths.env_file),
                setup_complete=is_setup_complete(current_settings()),
                error=str(exc),
            ), 400

        if action == "test":
            try:
                companies = document_reader().list_companies()
                message = (
                    f"Conexión correcta. Empresas encontradas: {len(companies)}"
                    if companies
                    else "Conexión correcta, pero no se devolvieron empresas."
                )
                return redirect(
                    url_for("app_setup", saved="1", test_ok=message)
                )
            except Exception as exc:
                return render_template(
                    "setup.html",
                    values=setup_form_values(),
                    env_file=str(paths.env_file),
                    setup_complete=is_setup_complete(current_settings()),
                    error=f"No se pudo conectar a Business Central: {exc}",
                ), 400

        return redirect(url_for("app_setup", saved="1"))

    @app.get("/")
    def index():
        if is_desktop_mode() and not is_setup_complete(current_settings()):
            return redirect(url_for("app_setup"))
        companies = load_companies()
        connection_error = None
        if not companies:
            connection_error = "Business Central no devolvió empresas"
        return render_template(
            "index.html",
            companies=companies,
            document_types=registry.all(),
            default_company=current_settings().company,
            connection_error=connection_error,
            form={},
            document=None,
            preview=None,
            diagnosis=None,
            enrichments=None,
            ai_conclusion=None,
            ai_pending=False,
            ai_request=None,
            ai_provider=current_settings().ai_provider,
            discovered_actions=None,
            error=None,
        )

    @app.post("/preview")
    def preview():
        company = request.form.get("company", "").strip()
        type_id = request.form.get("type_id", "").strip()
        action_id = request.form.get("action_id", "").strip()
        number = request.form.get("number", "").strip()
        form = {
            "company": company,
            "type_id": type_id,
            "action_id": action_id,
            "number": number,
        }
        error = None
        document = None
        preview_result = None
        diagnostic_report = None
        enrichments = None
        ai_conclusion = None
        ai_pending = False
        ai_request = None
        case_label = None
        primary_message = None

        try:
            if request.form.get("confirmed") != "yes":
                raise ValueError("Debe confirmar que desea ejecutar la acción")
            definition = registry.get(type_id)
            action = definition.action(action_id)
            if action.safety not in RUNNABLE_SAFETY_LEVELS:
                raise ValueError(
                    "La acción está bloqueada hasta que se revise su seguridad"
                )
            document = document_reader().find_document(
                company=company,
                definition=definition,
                number=number,
            )
            if not _preview_lock.acquire(blocking=False):
                raise PreviewError("Ya hay otra vista previa en ejecución")
            try:
                preview_result = BusinessCentralWebPreview(
                    current_settings(),
                    reports_dir=reports_dir,
                ).run(document, definition, action)
            finally:
                _preview_lock.release()

            if preview_result.messages:
                primary_message = primary_preview_message(preview_result.messages)
                diagnostic_report = build_diagnostic_service(
                    current_settings(),
                    _extension_catalog(current_settings()),
                ).diagnose(
                    Incident(
                        error_text=primary_message.description,
                        document_number=document.number,
                        company=document.company,
                        call_stack=primary_message.call_stack,
                        metadata={
                            "document_kind": document.kind,
                            "status": document.status,
                            "posting_date": document.posting_date,
                            "context": primary_message.context,
                            "context_field": primary_message.context_field,
                            "source": primary_message.source,
                            "source_field": primary_message.source_field,
                        },
                    )
                )
                sql_client = (
                    SqlReadOnlyClient(
                        current_settings().sql_connection_string
                    )
                    if current_settings().sql_connection_string
                    else None
                )
                enrichment_items = enrich_from_message(
                    primary_message,
                    document.company,
                    sql_client,
                )
                if enrichment_items:
                    enrichments = [
                        item.as_dict() for item in enrichment_items
                    ]
                case_label = f"{definition.label} / {action.label}"
                if current_settings().ai_enabled and diagnostic_report:
                    ai_pending = True
                    ai_request = _build_ai_request_payload(
                        case_label=case_label,
                        document=document,
                        message=primary_message,
                        diagnosis=diagnostic_report,
                        enrichments=enrichment_items,
                    )
        except (
            ConfigurationError,
            DocumentNotFoundError,
            KeyError,
            PreviewError,
            RuntimeError,
            ValueError,
        ) as exc:
            error = str(exc)

        companies = load_companies(company)
        return render_template(
            "index.html",
            companies=companies,
            document_types=registry.all(),
            default_company=current_settings().company,
            connection_error=None,
            form=form,
            document=asdict(document) if document else None,
            preview=asdict(preview_result) if preview_result else None,
            diagnosis=(
                diagnostic_report.as_dict() if diagnostic_report else None
            ),
            enrichments=enrichments,
            ai_conclusion=ai_conclusion,
            ai_pending=ai_pending,
            ai_request=ai_request,
            ai_provider=current_settings().ai_provider,
            discovered_actions=None,
            error=error,
        )

    @app.post("/preview/ai-conclusions")
    def preview_ai_conclusions():
        if not current_settings().ai_enabled:
            return jsonify({"error": "La IA no está configurada"}), 400
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Falta el cuerpo de la solicitud"}), 400
        try:
            result = _request_ai_conclusion_from_payload(
                payload,
                current_settings(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result.as_dict())

    @app.post("/preview/ai-focus-external")
    def focus_external_ai_tab():
        if current_settings().ai_provider not in _WEB_AI_PROVIDERS:
            return jsonify({"error": "Solo disponible con proveedores web"}), 400
        client = build_llm_client(current_settings())
        if not getattr(client, "cdp_available", False):
            return jsonify({"error": "Requiere AGENTEBC_AI_WEB_CDP_URL"}), 400
        try:
            client.focus_chat_tab()
        except (DeepSeekWebError, GoogleAiWebError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"ok": True})

    @app.post("/preview/ai-focus-deepseek")
    def focus_deepseek_tab():
        return focus_external_ai_tab()

    @app.post("/explore-actions")
    def explore_actions():
        company = request.form.get("company", "").strip()
        type_id = request.form.get("type_id", "").strip()
        number = request.form.get("number", "").strip()
        form = {
            "company": company,
            "type_id": type_id,
            "action_id": "",
            "number": number,
        }
        document = None
        exploration = None
        error = None
        try:
            definition = registry.get(type_id)
            document = document_reader().find_document(
                company=company,
                definition=definition,
                number=number,
            )
            if not _preview_lock.acquire(blocking=False):
                raise PreviewError("Ya hay otra sesión de navegador en ejecución")
            try:
                exploration = BusinessCentralActionExplorer(
                    current_settings(),
                    reports_dir=reports_dir,
                ).run(document, definition)
            finally:
                _preview_lock.release()
        except (
            ConfigurationError,
            DocumentNotFoundError,
            KeyError,
            PreviewError,
            RuntimeError,
            ValueError,
        ) as exc:
            error = str(exc)

        return render_template(
            "index.html",
            companies=load_companies(company),
            document_types=registry.all(),
            default_company=current_settings().company,
            connection_error=None,
            form=form,
            document=asdict(document) if document else None,
            preview=None,
            diagnosis=None,
            enrichments=None,
            ai_conclusion=None,
            ai_pending=False,
            ai_request=None,
            ai_provider=current_settings().ai_provider,
            discovered_actions=(
                asdict(exploration) if exploration else None
            ),
            error=error,
        )

    @app.get("/configuration")
    def configuration():
        type_id = request.args.get("type_id", "")
        action_id = request.args.get("action_id", "")
        try:
            editing_type = registry.get(type_id) if type_id else None
        except KeyError:
            editing_type = None
        try:
            editing_action = (
                editing_type.action(action_id)
                if editing_type and action_id
                else None
            )
        except KeyError:
            editing_action = None
        dialog_steps_text = ""
        field_edits_text = ""
        if editing_action and editing_action.dialog_steps:
            dialog_steps_text = format_dialog_steps_text(
                editing_action.dialog_steps
            )
        if editing_action and editing_action.field_edits:
            field_edits_text = format_field_edits_text(
                editing_action.field_edits
            )
        return render_template(
            "configuration.html",
            document_types=registry.all(),
            selected_type=type_id,
            editing_type=editing_type,
            editing_action=editing_action,
            dialog_steps_text=dialog_steps_text,
            field_edits_text=field_edits_text,
            discovered_label=request.args.get("action_label", ""),
            discovered_menu=request.args.get("menu_label", ""),
            saved=request.args.get("saved"),
            error=None,
        )

    @app.post("/configuration/document-type")
    def save_document_type():
        try:
            type_id = request.form.get("id", "").strip()
            try:
                current_actions = registry.get(type_id).actions
            except KeyError:
                current_actions = ()
            definition = DocumentTypeDefinition(
                id=type_id,
                label=request.form.get("label", "").strip(),
                page_id=int(request.form.get("page_id", "0")),
                source_table=request.form.get("source_table", "").strip(),
                odata_service=request.form.get("odata_service", "").strip(),
                odata_key_field=request.form.get(
                    "odata_key_field", ""
                ).strip(),
                odata_select_fields=_parse_pairs(
                    request.form.get("odata_select_fields", "")
                ),
                odata_filters=_parse_pairs(
                    request.form.get("odata_filters", "")
                ),
                page_filters=_parse_pairs(
                    request.form.get("page_filters", "")
                ),
                actions=current_actions,
            )
            registry.save_document_type(definition)
            return redirect(
                url_for("configuration", saved="document", type_id=type_id)
            )
        except (KeyError, TypeError, ValueError) as exc:
            return render_template(
                "configuration.html",
                document_types=registry.all(),
                selected_type=request.form.get("id", ""),
                editing_type=None,
                editing_action=None,
                dialog_steps_text="",
                field_edits_text="",
                discovered_label="",
                discovered_menu="",
                saved=None,
                error=str(exc),
            ), 400

    @app.post("/configuration/action")
    def save_action():
        try:
            type_id = request.form.get("type_id", "").strip()
            action = ActionDefinition(
                id=request.form.get("id", "").strip(),
                label=request.form.get("label", "").strip(),
                safety=request.form.get("safety", "blocked").strip(),
                menu_aria_label=(
                    request.form.get("menu_aria_label", "").strip() or None
                ),
                action_aria_label=(
                    request.form.get("action_aria_label", "").strip() or None
                ),
                result_markers=tuple(
                    marker.strip()
                    for marker in request.form.get(
                        "result_markers", ""
                    ).splitlines()
                    if marker.strip()
                ),
                parse_error_rows=(
                    request.form.get("parse_error_rows") == "yes"
                ),
                auto_confirm=request.form.get("auto_confirm") == "yes",
                dialog_steps=parse_dialog_steps_text(
                    request.form.get("dialog_steps", "")
                ),
                field_edits=parse_field_edits_text(
                    request.form.get("field_edits", "")
                ),
            )
            registry.save_action(type_id, action)
            return redirect(
                url_for("configuration", saved="action", type_id=type_id)
            )
        except (KeyError, ValueError) as exc:
            return render_template(
                "configuration.html",
                document_types=registry.all(),
                selected_type=request.form.get("type_id", ""),
                editing_type=None,
                editing_action=None,
                dialog_steps_text=request.form.get("dialog_steps", ""),
                field_edits_text=request.form.get("field_edits", ""),
                discovered_label=request.form.get("label", ""),
                discovered_menu=request.form.get("menu_aria_label", ""),
                saved=None,
                error=str(exc),
            ), 400

    @app.get("/reports/<path:filename>")
    def report_image(filename: str):
        return send_from_directory(reports_dir, filename)

    return app


def _parse_observed_at(value: str) -> datetime:
    normalized = value.strip()
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return parsedate_to_datetime(normalized)


def _serialize_diagnosis(diagnosis: DiagnosticReport) -> dict[str, object]:
    data = diagnosis.as_dict()
    incident = dict(data["incident"])
    observed_at = incident.get("observed_at")
    if isinstance(observed_at, datetime):
        incident["observed_at"] = observed_at.isoformat()
    data["incident"] = incident
    return data


def _build_ai_request_payload(
    *,
    case_label: str,
    document: DocumentReference,
    message: PreviewMessage,
    diagnosis: DiagnosticReport,
    enrichments: tuple[EvidenceItem, ...],
) -> dict[str, object]:
    return {
        "case_label": case_label,
        "document": asdict(document),
        "message": asdict(message),
        "diagnosis": _serialize_diagnosis(diagnosis),
        "enrichments": [item.as_dict() for item in enrichments],
    }


def _request_ai_conclusion_from_payload(
    payload: dict[str, object],
    settings: Settings,
):
    document = DocumentReference(**payload["document"])
    message = PreviewMessage(**payload["message"])
    diagnosis = _diagnosis_from_dict(payload["diagnosis"])
    enrichments = tuple(
        EvidenceItem(**item) for item in payload.get("enrichments", [])
    )
    return request_ai_conclusion(
        build_llm_client(settings),
        case_label=str(payload["case_label"]),
        document=document,
        message=message,
        diagnosis=diagnosis,
        enrichments=enrichments,
    )


def _diagnosis_from_dict(data: dict[str, object]) -> DiagnosticReport:
    incident_data = dict(data["incident"])
    observed_at = incident_data.get("observed_at")
    if isinstance(observed_at, str):
        incident_data["observed_at"] = _parse_observed_at(observed_at)
    return DiagnosticReport(
        incident=Incident(**incident_data),
        summary=str(data["summary"]),
        confidence=str(data["confidence"]),
        evidence=tuple(Evidence(**item) for item in data.get("evidence", [])),
        source_matches=tuple(
            SourceMatch(**item) for item in data.get("source_matches", [])
        ),
        proposed_solutions=tuple(
            ProposedSolution(**item) for item in data.get("proposed_solutions", [])
        ),
        limitations=tuple(str(item) for item in data.get("limitations", [])),
    )


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


def _parse_pairs(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(
                f"La línea {number} debe tener el formato campo=valor"
            )
        key, item = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Falta el campo en la línea {number}")
        result[key] = item.strip()
    return result


def main() -> None:
    try:
        app = create_app()
    except ConfigurationError as exc:
        raise SystemExit(f"Error de configuración: {exc}") from exc
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=not is_desktop_mode(),
        use_reloader=not is_desktop_mode(),
        threaded=True,
    )


if __name__ == "__main__":
    main()
