from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Frame, Locator, Page, TimeoutError, sync_playwright

from .browser import launch_browser
from .call_stack import extract_call_stack_text
from .config import Settings
from .document_types import (
    ActionDefinition,
    DialogStep,
    DocumentTypeDefinition,
    FieldEditStep,
)
from .documents import DocumentReference


class PreviewError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreviewMessage:
    message_type: str
    description: str
    context: str | None
    context_field: str | None
    source: str | None
    source_field: str | None
    additional_information: str | None
    call_stack: str | None


@dataclass(frozen=True, slots=True)
class WaitResult:
    outcome: str
    messages: tuple[PreviewMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class PreviewResult:
    outcome: str
    title: str
    messages: tuple[PreviewMessage, ...]
    raw_rows: tuple[str, ...]
    screenshot_path: Path


def primary_preview_message(
    messages: tuple[PreviewMessage, ...],
) -> PreviewMessage:
    """Elige el mensaje más útil para diagnosticar (pila, campo origen, etc.)."""
    if not messages:
        raise ValueError("No hay mensajes de vista previa")
    for message in messages:
        if message.call_stack:
            return message
    for message in messages:
        if message.source_field:
            return message
    for message in messages:
        if message.context == "Validación de campo":
            return message
    for message in messages:
        if message.additional_information:
            return message
    return messages[0]


@dataclass(frozen=True, slots=True)
class DiscoveredAction:
    label: str
    menu_aria_label: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class ActionExplorationResult:
    actions: tuple[DiscoveredAction, ...]
    screenshot_path: Path


class BusinessCentralWebPreview:
    """Automatiza exclusivamente la acción estándar Vista previa de registro."""

    def __init__(self, settings: Settings, *, reports_dir: Path | None = None) -> None:
        if not settings.odata_base_url:
            raise ValueError("Falta AGENTEBC_ODATA_BASE_URL")
        if not settings.username or not settings.password:
            raise ValueError("Faltan las credenciales web de Business Central")
        self._settings = settings
        self._web_base_url = settings.odata_base_url.rsplit("/ODataV4", 1)[0]
        self._reports_dir = reports_dir or (
            Path(__file__).resolve().parents[2] / "reports"
        )

    def run(
        self,
        document: DocumentReference,
        definition: DocumentTypeDefinition | None = None,
        action: ActionDefinition | None = None,
    ) -> PreviewResult:
        if definition is None or action is None:
            definition, action = _legacy_invoice_configuration(document)
        if action.safety == "blocked":
            raise PreviewError(
                f"La acción {action.label} está bloqueada hasta revisarla"
            )
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        url = self._document_url(document, definition)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        screenshot = self._reports_dir / (
            f"{_safe_filename(action.id)}-{_safe_filename(document.company)}-"
            f"{_safe_filename(document.number)}-{timestamp}.png"
        )

        with sync_playwright() as playwright:
            browser = launch_browser(playwright, self._settings)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}
                )
                self._grant_clipboard_permissions(context)
                page = context.new_page()
                page.set_default_timeout(15_000)
                stage = "navegación inicial"
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self._settings.request_timeout_seconds * 1000),
                )
                self._grant_clipboard_permissions(context, page.url)
                stage = "inicio de sesión"
                self._sign_in_if_needed(page)
                stage = "carga de la ficha"
                frame = self._wait_for_document_frame(page, action)
                field_messages: tuple[PreviewMessage, ...] = ()
                if action.field_edits:
                    stage = f"edición de campos de {action.label}"
                    field_messages = self._apply_field_edits(
                        frame,
                        action.field_edits,
                    )
                if action.menu_aria_label or action.action_aria_label:
                    stage = f"ejecución de {action.label}"
                    self._click_action(frame, action)
                stage = f"diálogos de {action.label}"
                dialog_progress = set[int]()
                if action.auto_confirm and action.dialog_steps:
                    self._wait_and_handle_dialogs(
                        page,
                        action,
                        dialog_progress,
                    )
                stage = f"resultado de {action.label}"
                if field_messages:
                    wait_result = WaitResult(
                        outcome="errors",
                        messages=field_messages,
                    )
                elif action.menu_aria_label or action.action_aria_label:
                    wait_result = self._wait_for_result(
                        page,
                        frame,
                        action,
                        dialog_progress,
                    )
                else:
                    wait_result = WaitResult(outcome="completed")
                stage = "lectura del resultado"
                rows = (
                    self._collect_error_rows(page)
                    if action.parse_error_rows
                    else self._collect_rows(page)
                )
                row_messages = (
                    tuple(_parse_error_rows(rows))
                    if action.parse_error_rows
                    else ()
                )
                page.screenshot(path=str(screenshot), full_page=False)
                self._dismiss_bc_message_dialogs(page)
                title = page.title()
                messages = wait_result.messages + row_messages
                return PreviewResult(
                    outcome="errors" if messages else wait_result.outcome,
                    title=title,
                    messages=messages,
                    raw_rows=rows,
                    screenshot_path=screenshot,
                )
            except TimeoutError as exc:
                raise PreviewError(
                    f"Business Central agotó el tiempo durante: {stage}"
                ) from exc
            finally:
                browser.close()

    def _document_url(
        self,
        document: DocumentReference,
        definition: DocumentTypeDefinition,
    ) -> str:
        escaped_number = document.number.replace("'", "''")
        filters = [
            f"'{definition.source_table}'.'No.' IS '{escaped_number}'"
        ]
        filters.extend(
            f"'{definition.source_table}'.'{field}' IS '{value.replace(chr(39), chr(39) * 2)}'"
            for field, value in definition.page_filters.items()
        )
        query = urlencode(
            {
                "company": document.company,
                "page": str(definition.page_id),
                "filter": " AND ".join(filters),
            }
        )
        return f"{self._web_base_url}/?{query}"

    def _sign_in_if_needed(self, page: Page) -> None:
        if "/SignIn" not in page.url and not page.locator(
            'input[type="password"]'
        ).count():
            return
        username = page.locator('input[type="text"]').first
        password = page.locator('input[type="password"]').first
        submit = page.get_by_role("button", name="Iniciar sesión")
        username.fill(self._settings.username or "")
        password.fill(self._settings.password or "")
        submit.evaluate("(element) => element.click()")

    def _wait_for_document_frame(
        self,
        page: Page,
        action: ActionDefinition,
    ) -> Frame:
        deadline = time.monotonic() + self._settings.request_timeout_seconds
        selectors: list[str] = []
        if action.menu_aria_label:
            selectors.append(
                f'button[aria-label="{_css_string(action.menu_aria_label)}"]'
            )
        if action.action_aria_label:
            selectors.append(
                f'button[aria-label="{_css_string(action.action_aria_label)}"]'
            )
        if action.field_edits:
            label = action.field_edits[0].field_label
            selectors.extend(
                [
                    f'[aria-label="{_css_string(label)}"]',
                    f'label:has-text("{_css_string(label)}")',
                    f'[controlname*="{_css_string(label)}" i]',
                ]
            )
            for control_name in _FIELD_CONTROL_NAMES.get(label.casefold(), ()):
                selectors.append(
                    f'[controlname="{_css_string(control_name)}"]'
                )
            selectors.extend(
                [
                    'button[title*="Realizar cambios" i]',
                    'button[title*="Make changes" i]',
                ]
            )
        if not selectors:
            raise PreviewError(
                f"La acción {action.label} no define selectores ni campos a editar"
            )
        while time.monotonic() < deadline:
            for frame in page.frames:
                for selector in selectors:
                    try:
                        if frame.locator(selector).count():
                            return frame
                    except Exception:
                        continue
            page.wait_for_timeout(500)
        raise PreviewError(f"No se encontró la ficha para {action.label}")

    def _apply_field_edits(
        self,
        frame: Frame,
        field_edits: tuple[FieldEditStep, ...],
    ) -> tuple[PreviewMessage, ...]:
        self._dismiss_bc_message_dialogs(frame.page)
        self._expand_collapsed_page_fields(frame)
        self._ensure_page_editable(frame.page, frame)
        for step in field_edits:
            self._apply_field_edit(frame, step)
            frame.page.wait_for_timeout(600)
        self._close_open_field_dropdowns(frame)
        return tuple(self._collect_page_validation_errors(frame))

    def _expand_collapsed_page_fields(self, frame: Frame) -> None:
        for selector in (
            'button[title*="Mostrar más" i]',
            'button[aria-label*="Mostrar más" i]',
            'button[title*="Show more" i]',
            'button[aria-label*="Show more" i]',
        ):
            try:
                buttons = frame.locator(selector)
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    if not button.is_visible():
                        continue
                    button.click(force=True)
                    frame.page.wait_for_timeout(400)
            except Exception:
                continue

    def _ensure_page_editable(self, page: Page, frame: Frame) -> None:
        if _page_is_editable(frame):
            return
        if _activate_edit_mode(page, frame):
            page.wait_for_timeout(700)
        if _page_is_editable(frame):
            return
        raise PreviewError(
            "La ficha está en modo consulta y no se pudo activar la edición. "
            "Revise permisos o el botón Editar en la captura."
        )

    def _apply_field_edit(self, frame: Frame, step: FieldEditStep) -> None:
        locator = _bc_field_locator(frame, step.field_label)
        if locator is None:
            raise PreviewError(
                f"No se encontró el campo {step.field_label} en la ficha"
            )
        if not _set_bc_field_value(frame, locator, step.value):
            raise PreviewError(
                f"No se pudo asignar el valor {step.value} al campo "
                f"{step.field_label}. Compruebe que la ficha está editable."
            )

    def _collect_page_validation_errors(self, frame: Frame) -> list[PreviewMessage]:
        messages: list[PreviewMessage] = []
        body = self._read_frame_body(frame)
        banner = _extract_page_error_banner(body)
        if banner:
            messages.append(
                PreviewMessage(
                    message_type="Error",
                    description=banner,
                    context="Validación de página",
                    context_field=None,
                    source=None,
                    source_field=None,
                    additional_information=None,
                    call_stack=None,
                )
            )
        for field_label, error_text in _find_field_validation_errors(frame):
            messages.append(
                PreviewMessage(
                    message_type="Error",
                    description=error_text,
                    context="Validación de campo",
                    context_field=field_label,
                    source=None,
                    source_field=None,
                    additional_information=None,
                    call_stack=None,
                )
            )
        if not messages and banner is None:
            for line in _extract_inline_error_lines(body):
                messages.append(
                    PreviewMessage(
                        message_type="Error",
                        description=line,
                        context="Validación de página",
                        context_field=None,
                        source=None,
                        source_field=None,
                        additional_information=None,
                        call_stack=None,
                    )
                )
        if messages:
            self._close_open_field_dropdowns(frame)
            _open_validation_popover(frame)
            body = self._read_frame_body(frame)
            for validation_line in _extract_field_validation_lines(body):
                if any(validation_line == item.description for item in messages):
                    continue
                messages.append(
                    PreviewMessage(
                        message_type="Error",
                        description=validation_line,
                        context="Validación de campo",
                        context_field=_extract_validation_field_name(validation_line),
                        source=None,
                        source_field=_extract_validation_target_field(validation_line),
                        additional_information=None,
                        call_stack=None,
                    )
                )
            shared_details = self._copy_visible_share_details(frame)
            if shared_details:
                messages = _merge_shared_details_into_messages(messages, shared_details)
        return messages

    @staticmethod
    def _read_frame_body(frame: Frame) -> str:
        try:
            return frame.locator("body").inner_text(timeout=2_000)
        except Exception:
            return ""

    def _close_open_field_dropdowns(self, frame: Frame) -> None:
        try:
            frame.page.keyboard.press("Tab")
            frame.page.wait_for_timeout(250)
        except Exception:
            pass

    def _copy_visible_share_details(self, frame: Frame) -> str | None:
        copied = self._copy_field_validation_share_details(frame)
        if copied:
            return copied
        scope = frame.locator("body")
        if _has_share_details_control(scope, frame):
            return self._copy_bc_error_details(frame, scope)
        return None

    def _copy_field_validation_share_details(self, frame: Frame) -> str | None:
        frame.page.wait_for_timeout(500)
        popover = _open_validation_popover(frame)
        if popover is None:
            return None
        if not _click_popover_share_button(frame, popover):
            return None
        frame.page.wait_for_timeout(400)
        self._install_copy_capture(frame.page)
        if not self._click_copy_error_details(
            frame.page,
            frame,
            frame.locator("body"),
        ):
            return None
        frame.page.wait_for_timeout(500)
        copied = self._read_captured_copy_text(frame.page)
        if copied:
            return copied
        return self._read_clipboard_text(frame.page)

    @staticmethod
    def _install_copy_capture(page: Page) -> None:
        try:
            page.evaluate(
                """() => {
                    window.__agentebcLastCopy = '';
                    document.addEventListener(
                        'copy',
                        (event) => {
                            const text = event.clipboardData
                                ? event.clipboardData.getData('text/plain')
                                : '';
                            if (text) {
                                window.__agentebcLastCopy = text;
                            }
                        },
                        true,
                    );
                }"""
            )
        except Exception:
            pass

    @staticmethod
    def _read_captured_copy_text(page: Page) -> str | None:
        try:
            text = page.evaluate("() => window.__agentebcLastCopy || ''")
        except Exception:
            return None
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None

    @staticmethod
    def _click_action(frame: Frame, action: ActionDefinition) -> None:
        if not action.menu_aria_label and not action.action_aria_label:
            return
        if action.menu_aria_label:
            menu = frame.locator(
                f'button[aria-label="{_css_string(action.menu_aria_label)}"]'
            )
            menu.first.evaluate("(element) => element.click()")
            frame.page.wait_for_timeout(300)
        action_button = BusinessCentralWebPreview._action_button_locator(
            frame,
            action,
        )
        action_button.wait_for(state="visible", timeout=10_000)
        action_button.evaluate("(element) => element.click()")

    @staticmethod
    def _action_button_locator(frame: Frame, action: ActionDefinition) -> Locator:
        label = action.action_aria_label or ""
        escaped = _css_string(label)
        if action.menu_aria_label:
            return frame.locator(
                f'button[role="menuitem"][aria-label="{escaped}"]'
            ).first
        candidates = frame.locator(f'button[aria-label="{escaped}"]')
        if candidates.count() == 1:
            return candidates.first
        top_level = frame.locator(
            f'button[aria-label="{escaped}"][data-top-level-action="true"]'
        )
        if top_level.count():
            return top_level.first
        return frame.locator(
            f'button[aria-label="{escaped}"]:not([data-top-level-action="true"])'
        ).first

    def _wait_and_handle_dialogs(
        self,
        page: Page,
        action: ActionDefinition,
        completed: set[int],
        *,
        timeout_seconds: float = 15.0,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._handle_dialogs(page, action, completed, max_clicks=2):
                if len(completed) >= len(action.dialog_steps):
                    return True
            elif len(completed) >= len(action.dialog_steps):
                return True
            page.wait_for_timeout(250)
        return len(completed) >= len(action.dialog_steps)

    def _handle_dialogs(
        self,
        page: Page,
        action: ActionDefinition,
        completed: set[int],
        *,
        max_clicks: int = 8,
    ) -> int:
        clicks = 0
        for _ in range(max_clicks):
            if not self._advance_dialog(page, action, completed):
                break
            clicks += 1
            page.wait_for_timeout(500)
        return clicks

    def _advance_dialog(
        self,
        page: Page,
        action: ActionDefinition,
        completed: set[int],
    ) -> bool:
        for index, step in enumerate(action.dialog_steps):
            if index in completed:
                continue
            frame = self._find_dialog_frame(page, step)
            if frame is None:
                return False
            if step.selection:
                self._select_dialog_option(frame, step.selection)
            button = self._dialog_button_locator(frame, step.button)
            if button is None:
                return False
            button.evaluate("(element) => element.click()")
            completed.add(index)
            return True
        return False

    def _find_dialog_frame(
        self,
        page: Page,
        step: DialogStep,
    ) -> Frame | None:
        for frame in page.frames:
            if self._dialog_step_visible(frame, step):
                return frame
        return None

    @staticmethod
    def _dialog_step_visible(frame: Frame, step: DialogStep) -> bool:
        try:
            dialogs = frame.locator('[role="dialog"], [role="alertdialog"]')
            for index in range(dialogs.count()):
                dialog = dialogs.nth(index)
                try:
                    if not dialog.is_visible():
                        continue
                except Exception:
                    continue
                text = dialog.inner_text(timeout=1_000)
                if _confirmation_visible(text, step.markers):
                    return True
            text = frame.locator("body").inner_text(timeout=1_000)
        except Exception:
            return False
        return _confirmation_visible(text, step.markers)

    @staticmethod
    def _select_dialog_option(frame: Frame, selection: str) -> None:
        radio = frame.get_by_role("radio", name=selection)
        if radio.count() and radio.first.is_visible():
            radio.first.evaluate("(element) => element.click()")
            return
        labeled = frame.get_by_label(selection)
        if labeled.count() and labeled.first.is_visible():
            labeled.first.evaluate("(element) => element.click()")
            return
        option = frame.get_by_text(selection, exact=True)
        if option.count() and option.first.is_visible():
            option.first.evaluate("(element) => element.click()")

    @staticmethod
    def _dialog_button_locator(frame: Frame, button_label: str) -> Locator | None:
        for selector in ('[role="dialog"]', '[role="alertdialog"]'):
            dialogs = frame.locator(f"{selector}:visible")
            for index in range(dialogs.count()):
                dialog = dialogs.nth(index)
                role_button = dialog.get_by_role("button", name=button_label)
                if role_button.count() and role_button.first.is_visible():
                    return role_button.first
                aria_button = dialog.locator(
                    f'button[aria-label="{_css_string(button_label)}"]'
                )
                if aria_button.count() and aria_button.first.is_visible():
                    return aria_button.first
        role_button = frame.get_by_role("button", name=button_label)
        if role_button.count():
            candidate = role_button.first
            if candidate.is_visible():
                return candidate
        aria_button = frame.locator(
            f'button[aria-label="{_css_string(button_label)}"]'
        )
        if aria_button.count() and aria_button.first.is_visible():
            return aria_button.first
        return None

    def _has_pending_dialog(
        self,
        page: Page,
        action: ActionDefinition,
        completed: set[int],
    ) -> bool:
        if not action.auto_confirm:
            return False
        for index, step in enumerate(action.dialog_steps):
            if index in completed:
                continue
            if self._find_dialog_frame(page, step) is not None:
                return True
        return False

    def _dialog_work_pending(
        self,
        page: Page,
        action: ActionDefinition,
        completed: set[int],
    ) -> bool:
        if not action.auto_confirm or not action.dialog_steps:
            return False
        if len(completed) < len(action.dialog_steps):
            return True
        return self._has_pending_dialog(page, action, completed)

    @staticmethod
    def _collect_rows(page: Page) -> tuple[str, ...]:
        rows: list[str] = []
        for frame in page.frames:
            try:
                rows.extend(
                    text.strip()
                    for text in frame.locator('[role="row"]').all_inner_texts()
                    if text.strip()
                )
            except Exception:
                continue
        return tuple(rows)

    def _collect_error_rows(self, page: Page) -> tuple[str, ...]:
        grid_rows = self._collect_error_rows_from_grid(page)
        if grid_rows:
            return grid_rows
        return self._collect_rows(page)

    def _collect_error_rows_from_grid(self, page: Page) -> tuple[str, ...]:
        rows: list[str] = []
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=1_000)
            except Exception:
                continue
            if not _is_error_messages_page(body):
                continue

            grids = frame.locator('[role="grid"]')
            for grid_index in range(grids.count()):
                grid = grids.nth(grid_index)
                try:
                    if not grid.is_visible():
                        continue
                except Exception:
                    continue

                headers = _read_grid_headers(grid)
                if headers and _is_complete_error_grid_headers(headers):
                    rows.append(_encode_error_grid_headers(headers))
                stack_col = (
                    _column_index_for_call_stack(headers) if headers else None
                )
                grid_rows = grid.locator('[role="row"]')
                for row_index in range(grid_rows.count()):
                    row = grid_rows.nth(row_index)
                    try:
                        if not row.is_visible():
                            continue
                    except Exception:
                        continue

                    values = self._read_error_grid_row(frame, row, stack_col)
                    if not values or _is_error_message_header_row(values):
                        continue
                    if not _is_message_type_label(values[0]):
                        continue
                    rows.append("\t".join(values))

        return tuple(rows)

    def _read_error_grid_row(
        self,
        frame: Frame,
        row: Locator,
        stack_col: int | None,
    ) -> list[str]:
        cells = row.locator('[role="gridcell"], [role="cell"]')
        count = cells.count()
        if count == 0:
            return []

        values: list[str] = []
        for index in range(count):
            cell = cells.nth(index)
            if stack_col is not None and index == stack_col:
                values.append(self._read_call_stack_cell(frame, cell))
            else:
                values.append(_read_grid_cell_text(cell))
        return values

    def _read_call_stack_cell(self, frame: Frame, cell: Locator) -> str:
        page = frame.page
        try:
            cell.scroll_into_view_if_needed(timeout=2_000)
        except Exception:
            pass

        text = _read_grid_cell_deep_text(cell)
        if extract_call_stack_text(text):
            return text

        if _looks_like_call_stack_fragment(text):
            copied = self._try_copy_grid_cell(page, cell)
            if copied:
                return copied
            expanded = self._try_expand_call_stack_cell(frame, cell)
            if expanded:
                return expanded

        return text

    def _try_copy_grid_cell(self, page: Page, cell: Locator) -> str | None:
        try:
            cell.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Control+C")
            page.wait_for_timeout(250)
            copied = self._read_clipboard_text(page)
        except Exception:
            return None
        if copied and extract_call_stack_text(copied):
            return extract_call_stack_text(copied)
        return None

    def _try_expand_call_stack_cell(self, frame: Frame, cell: Locator) -> str | None:
        try:
            cell.dblclick(timeout=1_500)
            frame.page.wait_for_timeout(400)
            text = _read_grid_cell_deep_text(cell)
            if extract_call_stack_text(text):
                return text
            body = frame.locator("body").inner_text(timeout=1_000)
            stack = extract_call_stack_text(body)
            if stack:
                return stack
        except Exception:
            return None
        return None

    def _wait_for_result(
        self,
        page: Page,
        frame: Frame,
        action: ActionDefinition,
        dialog_progress: set[int],
    ) -> WaitResult:
        deadline = time.monotonic() + self._settings.request_timeout_seconds
        settle_after = None
        while time.monotonic() < deadline:
            if action.auto_confirm:
                self._handle_dialogs(page, action, dialog_progress, max_clicks=1)
            bc_message = self._peek_bc_message_dialog(
                page,
                action,
                dialog_progress,
            )
            if bc_message is not None:
                return WaitResult(outcome="errors", messages=(bc_message,))
            combined = "\n".join(self._visible_texts(page, frame))
            if "Mensajes de error" in combined:
                return WaitResult(outcome="errors")
            if self._dialog_work_pending(page, action, dialog_progress):
                settle_after = None
                page.wait_for_timeout(500)
                continue
            if action.result_markers and any(
                marker in combined for marker in action.result_markers
            ):
                return WaitResult(outcome="completed")
            if action.result_markers:
                page.wait_for_timeout(500)
                continue
            if settle_after is None:
                settle_after = time.monotonic() + 3
            elif time.monotonic() >= settle_after:
                return WaitResult(outcome="completed")
            page.wait_for_timeout(500)
        if self._has_pending_dialog(page, action, dialog_progress):
            return WaitResult(outcome="pending_confirmation")
        if action.auto_confirm and len(dialog_progress) < len(action.dialog_steps):
            return WaitResult(outcome="pending_confirmation")
        bc_message = self._peek_bc_message_dialog(
            page,
            action,
            dialog_progress,
        )
        if bc_message is not None:
            return WaitResult(outcome="errors", messages=(bc_message,))
        if action.result_markers:
            raise PreviewError("No se pudo determinar el resultado de la acción")
        return WaitResult(outcome="completed")

    def _peek_bc_message_dialog(
        self,
        page: Page,
        action: ActionDefinition,
        dialog_progress: set[int],
    ) -> PreviewMessage | None:
        if action.auto_confirm and len(dialog_progress) < len(action.dialog_steps):
            return None
        for frame in page.frames:
            try:
                dialogs = frame.locator('[role="dialog"]')
                for index in range(dialogs.count()):
                    dialog = dialogs.nth(index)
                    if not dialog.is_visible():
                        continue
                    text = dialog.inner_text(timeout=1_000)
                    if self._matches_pending_dialog_step(
                        text,
                        action,
                        dialog_progress,
                    ):
                        continue
                    message, call_stack, details = self._read_bc_message_dialog(
                        frame,
                        dialog,
                    )
                    if message is None:
                        continue
                    if not self._dialog_button_locator(frame, "Aceptar"):
                        if not self._dialog_button_locator(frame, "OK"):
                            continue
                    return PreviewMessage(
                        message_type="Error",
                        description=message,
                        context=None,
                        context_field=None,
                        source=None,
                        source_field=None,
                        additional_information=details,
                        call_stack=call_stack,
                    )
            except Exception:
                continue
        return None

    def _read_bc_message_dialog(
        self,
        frame: Frame,
        dialog: Locator,
    ) -> tuple[str | None, str | None, str | None]:
        initial_text = dialog.inner_text(timeout=1_000)
        message = _extract_bc_dialog_message(initial_text)
        call_stack = extract_call_stack_text(initial_text)
        details = _extract_bc_dialog_details(initial_text)

        if call_stack is None and _has_share_details_control(dialog, frame):
            copied_details = self._copy_bc_error_details(frame, dialog)
            if copied_details:
                call_stack = extract_call_stack_text(copied_details)
                details = copied_details.strip()
            if message is None and copied_details:
                message = _extract_bc_dialog_message(copied_details)

        return message, call_stack, details

    @staticmethod
    def _grant_clipboard_permissions(context, url: str | None = None) -> None:
        origins = ["*"]
        if url:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                origins = [f"{parsed.scheme}://{parsed.netloc}"]
        for origin in origins:
            try:
                context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin=origin,
                )
            except Exception:
                continue

    def _copy_bc_error_details(self, frame: Frame, dialog: Locator) -> str | None:
        page = frame.page
        if not self._open_share_details_menu(frame, dialog):
            return None
        self._install_copy_capture(page)
        if not self._click_copy_error_details(page, frame, dialog):
            return None
        page.wait_for_timeout(300)
        copied = self._read_captured_copy_text(page)
        if copied:
            return copied
        return self._read_clipboard_text(page)

    def _open_share_details_menu(self, frame: Frame, dialog: Locator) -> bool:
        for label in _SHARE_DETAILS_LABELS:
            for scope in (dialog, frame.locator("body")):
                candidates = (
                    scope.get_by_role("button", name=label),
                    scope.get_by_text(label, exact=True),
                    scope.locator(f'button[title*="{_css_string(label)}" i]'),
                    scope.locator(f'button[aria-label*="{_css_string(label)}" i]'),
                    scope.locator(
                        f'[role="button"][title*="{_css_string(label)}" i]'
                    ),
                )
                for control in candidates:
                    try:
                        if not control.count():
                            continue
                        candidate = control.first
                        if not candidate.is_visible():
                            continue
                        candidate.evaluate("(element) => element.click()")
                        frame.page.wait_for_timeout(400)
                        return True
                    except Exception:
                        continue
        return False

    def _click_copy_error_details(
        self,
        page: Page,
        frame: Frame,
        dialog: Locator,
    ) -> bool:
        for label in _COPY_ERROR_DETAILS_LABELS:
            scopes: list[Locator] = [dialog, frame.locator("body")]
            scopes.extend(frame.locator('[role="menu"]').all())
            for scope in scopes:
                for locator in (
                    scope.get_by_role("menuitem", name=label),
                    scope.get_by_role("option", name=label),
                    scope.get_by_text(label, exact=True),
                    scope.locator(f'[title*="{_css_string(label)}" i]'),
                ):
                    try:
                        if not locator.count():
                            continue
                        candidate = locator.first
                        if not candidate.is_visible():
                            continue
                        candidate.evaluate("(element) => element.click()")
                        return True
                    except Exception:
                        continue
            for candidate_frame in page.frames:
                try:
                    control = candidate_frame.get_by_role("menuitem", name=label)
                    if not control.count():
                        control = candidate_frame.get_by_text(label, exact=True)
                    if control.count() and control.first.is_visible():
                        control.first.evaluate("(element) => element.click()")
                        return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _read_clipboard_text(page: Page) -> str | None:
        for script in (
            "async () => await navigator.clipboard.readText()",
            """() => {
                const textarea = document.createElement('textarea');
                document.body.appendChild(textarea);
                textarea.focus();
                const ok = document.execCommand('paste');
                const value = textarea.value;
                textarea.remove();
                return ok ? value : '';
            }""",
        ):
            try:
                text = page.evaluate(script)
            except Exception:
                continue
            if isinstance(text, str) and text.strip():
                return text.strip()
        return None

    def _dismiss_bc_message_dialogs(self, page: Page) -> None:
        for frame in page.frames:
            try:
                dialogs = frame.locator('[role="dialog"]:visible')
                if not dialogs.count():
                    continue
                for button_label in ("Aceptar", "OK"):
                    button = self._dialog_button_locator(frame, button_label)
                    if button is not None:
                        button.evaluate("(element) => element.click()")
                        page.wait_for_timeout(200)
                        break
            except Exception:
                continue

    @staticmethod
    def _matches_pending_dialog_step(
        text: str,
        action: ActionDefinition,
        dialog_progress: set[int],
    ) -> bool:
        for index, step in enumerate(action.dialog_steps):
            if index in dialog_progress:
                continue
            if _confirmation_visible(text, step.markers):
                return True
        return False

    @staticmethod
    def _visible_texts(page: Page, frame: Frame) -> list[str]:
        texts: list[str] = []
        for candidate in page.frames:
            try:
                texts.append(candidate.locator("body").inner_text(timeout=1_000))
            except Exception:
                continue
        if not texts:
            try:
                texts.append(frame.locator("body").inner_text(timeout=1_000))
            except Exception:
                pass
        return texts


class BusinessCentralActionExplorer:
    """Enumera acciones visibles sin ejecutar ninguna acción de negocio."""

    def __init__(self, settings: Settings, *, reports_dir: Path | None = None) -> None:
        self._settings = settings
        self._helper = BusinessCentralWebPreview(
            settings,
            reports_dir=reports_dir,
        )
        self._reports_dir = self._helper._reports_dir

    def run(
        self,
        document: DocumentReference,
        definition: DocumentTypeDefinition,
    ) -> ActionExplorationResult:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        url = self._helper._document_url(document, definition)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        screenshot = self._reports_dir / (
            f"actions-{_safe_filename(document.company)}-"
            f"{_safe_filename(definition.id)}-{timestamp}.png"
        )

        with sync_playwright() as playwright:
            browser = launch_browser(playwright, self._settings)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(15_000)
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self._settings.request_timeout_seconds * 1000),
                )
                self._helper._sign_in_if_needed(page)
                frame = self._wait_for_action_frame(page)
                actions = self._collect_actions(frame)
                page.screenshot(path=str(screenshot), full_page=False)
                return ActionExplorationResult(
                    actions=tuple(actions),
                    screenshot_path=screenshot,
                )
            except TimeoutError as exc:
                raise PreviewError(
                    "Business Central agotó el tiempo explorando acciones"
                ) from exc
            finally:
                browser.close()

    def _wait_for_action_frame(self, page: Page) -> Frame:
        deadline = time.monotonic() + self._settings.request_timeout_seconds
        while time.monotonic() < deadline:
            candidates: list[tuple[int, Frame]] = []
            for frame in page.frames:
                try:
                    count = frame.locator(
                        'button[data-top-level-action="true"][aria-label]'
                    ).count()
                    if count:
                        candidates.append((count, frame))
                except Exception:
                    continue
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]
            page.wait_for_timeout(500)
        raise PreviewError("No se encontró una ficha con acciones visibles")

    @staticmethod
    def _collect_actions(frame: Frame) -> list[DiscoveredAction]:
        found: dict[tuple[str, str | None], DiscoveredAction] = {}
        direct_buttons = frame.locator(
            'button[data-top-level-action="true"][aria-label]'
        )
        for index in range(direct_buttons.count()):
            button = direct_buttons.nth(index)
            if not button.is_visible():
                continue
            label = (button.get_attribute("aria-label") or "").strip()
            if label:
                found[(label, None)] = DiscoveredAction(
                    label=label,
                    menu_aria_label=None,
                    title=_optional_attribute(button.get_attribute("title")),
                )

        menu_buttons = frame.locator(
            'button[aria-haspopup="true"][aria-label],'
            'button[title^="Acciones relacionadas"][aria-label]'
        )
        for index in range(menu_buttons.count()):
            menu = menu_buttons.nth(index)
            if not menu.is_visible():
                continue
            menu_label = (menu.get_attribute("aria-label") or "").strip()
            if not menu_label:
                continue
            try:
                menu.evaluate("(element) => element.click()")
                frame.page.wait_for_timeout(120)
                items = frame.locator(
                    'button[role="menuitem"][aria-label]:visible'
                )
                for item_index in range(items.count()):
                    item = items.nth(item_index)
                    label = (item.get_attribute("aria-label") or "").strip()
                    if label:
                        found[(label, menu_label)] = DiscoveredAction(
                            label=label,
                            menu_aria_label=menu_label,
                            title=_optional_attribute(
                                item.get_attribute("title")
                            ),
                        )
            except Exception:
                continue
            finally:
                frame.page.keyboard.press("Escape")

        return sorted(
            found.values(),
            key=lambda item: ((item.menu_aria_label or ""), item.label),
        )


_ERROR_GRID_HEADER_PREFIX = "__HEADERS__"
_ERROR_FIELD_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "message_type": ("tipo de mensaje", "message type"),
    "description": ("descripción", "description"),
    "context": ("contexto", "context"),
    "context_field": ("campo de contexto", "context field", "campo"),
    "source": ("origen", "source"),
    "source_field": ("campo origen", "source field", "origin field"),
    "additional_information": (
        "información adicional",
        "additional information",
        "información para el departamento",
        "información",
        "information",
    ),
    "call_stack": (
        "pila de llamadas",
        "call stack",
        "error call stack",
    ),
}


def _encode_error_grid_headers(headers: list[str]) -> str:
    return _ERROR_GRID_HEADER_PREFIX + "\t" + "\t".join(headers)


def _decode_error_grid_headers(row: str) -> list[str] | None:
    if not row.startswith(_ERROR_GRID_HEADER_PREFIX + "\t"):
        return None
    return [
        value.strip()
        for value in row.split("\t")[1:]
        if value.strip()
    ]


def _looks_like_error_grid_headers(headers: list[str]) -> bool:
    joined = " ".join(headers).casefold()
    return "tipo de mensaje" in joined or "message type" in joined


def _is_complete_error_grid_headers(headers: list[str]) -> bool:
    if not _looks_like_error_grid_headers(headers):
        return False
    joined = " ".join(headers).casefold()
    return (
        "origen" in joined
        or "source" in joined
        or "pila de llamadas" in joined
        or "call stack" in joined
    )


def _error_column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized = [(index, header.casefold().strip()) for index, header in enumerate(headers)]
    field_order = (
        "source_field",
        "context_field",
        "additional_information",
        "call_stack",
        "source",
        "context",
        "description",
        "message_type",
    )
    for field in field_order:
        for alias in _ERROR_FIELD_HEADER_ALIASES[field]:
            for index, header in normalized:
                if alias not in header:
                    continue
                if field == "context_field" and "origen" in header:
                    continue
                if field == "additional_information" and "soporte" in header:
                    continue
                mapping.setdefault(field, index)
    return mapping


def _message_from_error_row(
    values: list[str],
    headers: list[str] | None,
) -> PreviewMessage | None:
    if not values or not _is_message_type_label(values[0]):
        return None

    def value_at(index: int | None) -> str | None:
        if index is None or index >= len(values):
            return None
        text = values[index].strip()
        return text or None

    if headers:
        column_map = _error_column_map(headers)
        call_stack = value_at(column_map.get("call_stack"))
        message = PreviewMessage(
            message_type=value_at(column_map.get("message_type")) or values[0],
            description=value_at(column_map.get("description")) or "",
            context=value_at(column_map.get("context")),
            context_field=value_at(column_map.get("context_field")),
            source=value_at(column_map.get("source")),
            source_field=value_at(column_map.get("source_field")),
            additional_information=value_at(column_map.get("additional_information")),
            call_stack=call_stack,
        )
    else:
        padded = values + [None] * 10
        message = PreviewMessage(
            message_type=padded[0] or "",
            description=padded[1] or "",
            context=padded[2],
            context_field=padded[3],
            source=padded[4],
            source_field=padded[5],
            additional_information=padded[6],
            call_stack=None,
        )

    call_stack = message.call_stack or _find_call_stack_in_values(tuple(values))
    return _normalize_error_message(
        PreviewMessage(
            message_type=message.message_type,
            description=message.description,
            context=message.context,
            context_field=message.context_field,
            source=message.source,
            source_field=message.source_field,
            additional_information=message.additional_information,
            call_stack=call_stack,
        )
    )


def _normalize_error_message(message: PreviewMessage) -> PreviewMessage:
    call_stack = message.call_stack
    source = message.source
    source_field = message.source_field
    context_field = message.context_field
    additional_information = message.additional_information

    if source and (
        extract_call_stack_text(source)
        or _looks_like_call_stack_fragment(source)
        or "Customer(Table" in source
    ):
        call_stack = call_stack or extract_call_stack_text(source) or source
        source = None

    if context_field and _looks_like_support_hint(context_field):
        additional_information = additional_information or context_field
        context_field = None

    if source_field and _looks_like_timestamp(source_field):
        source_field = None

    if not source:
        customer_no = _extract_customer_number_from_text(
            " ".join(
                part
                for part in (
                    message.description,
                    message.context,
                    message.additional_information,
                    call_stack,
                )
                if part
            )
        )
        if customer_no:
            source = f"Customer: {customer_no}"

    return PreviewMessage(
        message_type=message.message_type,
        description=message.description,
        context=message.context,
        context_field=context_field,
        source=source,
        source_field=source_field,
        additional_information=additional_information,
        call_stack=call_stack,
    )


def _looks_like_support_hint(value: str) -> bool:
    lowered = value.casefold()
    return (
        "comprobar campos" in lowered
        or "check document fields" in lowered
        or lowered.startswith("http://")
        or lowered.startswith("https://")
    )


def _looks_like_timestamp(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2})?",
            value.strip(),
        )
    )


def _extract_customer_number_from_text(text: str) -> str | None:
    match = re.search(
        r"cliente\s+([0-9A-Z][0-9A-Z\-]*)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match = re.search(
        r"customer\s+([0-9A-Z][0-9A-Z\-]*)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def _parse_error_rows(rows: tuple[str, ...]) -> list[PreviewMessage]:
    messages: list[PreviewMessage] = []
    current_headers: list[str] | None = None
    for row in rows:
        decoded_headers = _decode_error_grid_headers(row)
        if decoded_headers is not None:
            current_headers = decoded_headers
            continue
        values = [
            value.strip()
            for value in re.split(r"[\t\r\n]+", row)
            if value.strip()
        ]
        if not values or _is_error_message_header_row(values):
            if _is_complete_error_grid_headers(values):
                current_headers = values
            continue
        message = _message_from_error_row(values, current_headers)
        if message is not None:
            messages.append(message)
    return messages


def _is_error_messages_page(body: str) -> bool:
    lowered = body.casefold()
    return "mensajes de error" in lowered or "error messages" in lowered


def _is_message_type_label(value: str) -> bool:
    return value.casefold() in {"error", "advertencia", "warning"}


def _is_error_message_header_row(values: list[str]) -> bool:
    joined = " ".join(values).casefold()
    return "tipo de mensaje" in joined or "message type" in joined


def _read_grid_headers(grid: Locator) -> list[str]:
    headers: list[str] = []
    header_cells = grid.locator(
        '[role="columnheader"], [role="row"] [role="columnheader"]'
    )
    if header_cells.count():
        for index in range(header_cells.count()):
            headers.append(_read_grid_cell_text(header_cells.nth(index)))
        return headers

    first_row = grid.locator('[role="row"]').first
    if not first_row.count():
        return headers
    for cell in first_row.locator('[role="gridcell"], [role="cell"]').all():
        headers.append(_read_grid_cell_text(cell))
    return headers


def _column_index_for_call_stack(headers: list[str]) -> int | None:
    markers = (
        "pila de llamadas",
        "call stack",
        "error call stack",
    )
    for index, header in enumerate(headers):
        lowered = header.casefold()
        if any(marker in lowered for marker in markers):
            return index
    return None


def _read_grid_cell_text(cell: Locator) -> str:
    try:
        return cell.inner_text(timeout=500).strip()
    except Exception:
        return ""


def _read_grid_cell_deep_text(cell: Locator) -> str:
    for attribute in ("aria-label", "title"):
        try:
            value = cell.get_attribute(attribute)
        except Exception:
            value = None
        if value and value.strip():
            return value.strip()
    try:
        deep = cell.evaluate(
            """(element) => {
                const collect = (node) => {
                    let best = '';
                    const push = (value) => {
                        const text = (value || '').trim();
                        if (text.length > best.length) best = text;
                    };
                    push(node.getAttribute?.('aria-label'));
                    push(node.getAttribute?.('title'));
                    push(node.textContent);
                    for (const child of node.children || []) {
                        push(collect(child));
                    }
                    return best;
                };
                return collect(element);
            }"""
        )
        if isinstance(deep, str) and deep.strip():
            return deep.strip()
    except Exception:
        pass
    return _read_grid_cell_text(cell)


def _looks_like_call_stack_fragment(value: str) -> bool:
    lowered = value.casefold()
    return '"(' in value and (
        "codeunit" in lowered
        or "pageextension" in lowered
        or "page" in lowered
        or "table" in lowered
        or "report" in lowered
    )


def _find_call_stack_in_values(values: tuple[str, ...]) -> str | None:
    for value in reversed(values):
        stack = extract_call_stack_text(value)
        if stack:
            return stack
    return extract_call_stack_text("\n".join(values))


_EDIT_BUTTON_LABELS = (
    "Edit",
    "Editar",
    "Modificar",
    "Edit record",
    "Editar registro",
    "Editar ficha",
    "Realizar cambios en la página",
    "Make changes to this page",
)
_EDIT_MODE_MARKERS = (
    "Guardar",
    "Save",
    "Descartar",
    "Discard",
    "Descartar cambios",
    "Discard changes",
)
_EDIT_MODE_ACTIVE_PATTERNS = (
    "solo lectura",
    "read-only",
    "readonly",
)
_EDIT_ACTIVATE_PATTERNS = (
    "Realizar cambios",
    "Make changes",
    "Edit",
    "Editar",
    "Modificar",
)
_EDIT_SHORTCUTS = ("Control+e", "Alt+e")


def _page_is_editable(frame: Frame) -> bool:
    for pattern in _EDIT_MODE_ACTIVE_PATTERNS:
        locator = frame.locator(f'button[title*="{_css_string(pattern)}" i]')
        try:
            if locator.count() and locator.first.is_visible():
                return True
        except Exception:
            continue
    for label in _EDIT_MODE_MARKERS:
        button = frame.get_by_role("button", name=label)
        try:
            if button.count() and button.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _activate_edit_mode(page: Page, frame: Frame) -> bool:
    for scope in (frame, page):
        for partial in _EDIT_ACTIVATE_PATTERNS:
            locator = scope.locator(
                f'button[aria-label*="{_css_string(partial)}" i],'
                f'button[title*="{_css_string(partial)}" i]'
            )
            try:
                if locator.count() and locator.first.is_visible():
                    locator.first.click()
                    return True
            except Exception:
                pass
        for label in _EDIT_BUTTON_LABELS:
            for locator in (
                scope.get_by_role("button", name=label),
                scope.locator(f'button[aria-label="{_css_string(label)}"]'),
                scope.locator(f'button[title="{_css_string(label)}"]'),
            ):
                try:
                    if not locator.count():
                        continue
                    candidate = locator.first
                    if not candidate.is_visible():
                        continue
                    candidate.click()
                    return True
                except Exception:
                    continue
    for shortcut in _EDIT_SHORTCUTS:
        try:
            page.keyboard.press(shortcut)
            page.wait_for_timeout(400)
            if _page_is_editable(frame):
                return True
        except Exception:
            continue
    return False


_PAGE_ERROR_BANNER_PATTERN = re.compile(
    r"la página tiene\s+(\d+)\s+errores?|the page has\s+(\d+)\s+errors?",
    re.IGNORECASE,
)


def _extract_page_error_banner(body: str) -> str | None:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _PAGE_ERROR_BANNER_PATTERN.search(line):
            return line
    return None


def _extract_inline_error_lines(body: str) -> tuple[str, ...]:
    if _PAGE_ERROR_BANNER_PATTERN.search(body):
        return ()
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line in _SKIP_DIALOG_LINES:
            continue
        lowered = line.casefold()
        if "debe tener un valor" in lowered or "must have a value" in lowered:
            lines.append(line)
        elif "no puede" in lowered or "cannot" in lowered:
            lines.append(line)
    return tuple(dict.fromkeys(lines))


_FIELD_CONTROL_NAMES: dict[str, tuple[str, ...]] = {
    "estado": ("Estado Contrato",),
}


def _bc_field_locator(frame: Frame, label: str) -> Locator | None:
    control_names = _FIELD_CONTROL_NAMES.get(label.casefold(), ())
    candidates: list[Locator] = []
    for control_name in control_names:
        candidates.append(
            frame.locator(f'[controlname="{_css_string(control_name)}"]')
            .locator('[role="textbox"], [role="combobox"], input, textarea')
        )
    candidates.extend(
        [
            frame.get_by_label(label, exact=True),
            frame.get_by_label(label),
            frame.locator(f'[aria-label="{_css_string(label)}"]'),
            frame.get_by_role("combobox", name=label),
            frame.get_by_role("textbox", name=label),
            frame.locator(
                f'[data-caption="{_css_string(label)}"],'
                f'[data-fieldcaption="{_css_string(label)}"]'
            ),
        ]
    )
    for candidate in candidates:
        try:
            if candidate.count() and candidate.first.is_visible():
                return candidate.first
        except Exception:
            continue
    return _bc_field_locator_near_caption(frame, label)


def _bc_field_locator_near_caption(frame: Frame, label: str) -> Locator | None:
    caption = frame.get_by_text(label, exact=True)
    try:
        if not caption.count():
            return None
        for index in range(min(caption.count(), 5)):
            marker = caption.nth(index)
            if not marker.is_visible():
                continue
            row = marker.locator(
                "xpath=ancestor::*[self::tr or self::div][1]"
            ).locator(
                '[role="combobox"], [role="textbox"], input, textarea, '
                '[contenteditable="true"]'
            )
            if row.count() and row.first.is_visible():
                return row.first
    except Exception:
        return None
    return None


def _set_bc_field_value(frame: Frame, locator: Locator, value: str) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    locator.click()
    frame.page.wait_for_timeout(250)
    try:
        locator.dblclick(timeout=1_000)
        frame.page.wait_for_timeout(200)
    except Exception:
        pass

    selected = _select_dropdown_value(frame, value)
    if not selected:
        for key in ("Alt+ArrowDown", "F4", "ArrowDown"):
            try:
                frame.page.keyboard.press(key)
                frame.page.wait_for_timeout(350)
            except Exception:
                continue
            if _select_dropdown_value(frame, value):
                selected = True
                break

    if selected:
        frame.page.keyboard.press("Tab")
        frame.page.wait_for_timeout(300)
        return _field_contains_value(locator, value)

    try:
        locator.fill(value)
    except Exception:
        frame.page.keyboard.type(value, delay=30)
    frame.page.keyboard.press("Tab")
    frame.page.wait_for_timeout(300)
    return _field_contains_value(locator, value)


def _select_dropdown_value(frame: Frame, value: str) -> bool:
    selectors: list[Locator] = [
        frame.get_by_role("option", name=value, exact=True),
        frame.get_by_role("menuitem", name=value, exact=True),
        frame.get_by_role("option", name=value),
        frame.get_by_role("menuitem", name=value),
        frame.get_by_text(value, exact=True),
    ]
    for selector in selectors:
        try:
            if selector.count() and selector.first.is_visible():
                selector.first.click()
                return True
        except Exception:
            continue
    return False


def _field_contains_value(locator: Locator, value: str) -> bool:
    try:
        current = locator.input_value(timeout=500)
        if value.casefold() in current.casefold():
            return True
    except Exception:
        pass
    try:
        text = locator.inner_text(timeout=500).strip()
        if value.casefold() in text.casefold():
            return True
    except Exception:
        pass
    return False


def _find_field_validation_errors(frame: Frame) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    invalid_fields = frame.locator('[aria-invalid="true"]')
    for index in range(invalid_fields.count()):
        field = invalid_fields.nth(index)
        try:
            if not field.is_visible():
                continue
        except Exception:
            continue
        label = (
            field.get_attribute("aria-label")
            or field.get_attribute("name")
            or f"Campo {index + 1}"
        )
        error_text = _read_field_error_text(frame, field)
        if error_text and not _looks_like_enum_dropdown_text(error_text):
            results.append((label.strip(), error_text.strip()))
    return results


def _read_field_error_text(frame: Frame, field: Locator) -> str | None:
    for attribute in ("aria-errormessage", "title", "aria-description"):
        message_id = field.get_attribute(attribute)
        if not message_id:
            continue
        if attribute == "aria-errormessage":
            target = frame.locator(f"#{_css_string(message_id)}")
            if target.count():
                text = target.first.inner_text(timeout=500).strip()
                if text:
                    return text
        elif message_id.strip() and attribute != "title":
            return message_id.strip()
    described_by = field.get_attribute("aria-describedby")
    if described_by:
        for part in described_by.split():
            target = frame.locator(f"#{_css_string(part)}")
            if target.count():
                text = target.first.inner_text(timeout=500).strip()
                if text:
                    return text
    container = field.locator(
        'xpath=ancestor::div[contains(@class,"ms-nav-edit-control-container")][1]'
    )
    if container.count():
        for selector in (
            '[role="tooltip"]',
            '[class*="validation"]',
            '[class*="error-message"]',
            '[class*="error"]',
        ):
            bubble = container.locator(selector)
            try:
                if bubble.count() and bubble.first.is_visible():
                    text = bubble.first.inner_text(timeout=500).strip()
                    if text and text not in _SKIP_DIALOG_LINES:
                        return text
            except Exception:
                continue
    return _read_visible_validation_tooltip(frame)


def _looks_like_enum_dropdown_text(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    enum_markers = {
        "pendiente de firma",
        "firmado",
        "anulado",
        "cancelado",
        "sin montar",
        "modificado",
    }
    matches = sum(1 for line in lines if line.casefold() in enum_markers)
    return matches >= 3


def _read_visible_validation_tooltip(frame: Frame) -> str | None:
    for selector in (
        '[role="tooltip"]:visible',
        '[class*="validation-result"]:visible',
        '[class*="validation-message"]:visible',
    ):
        try:
            tooltip = frame.locator(selector)
            if not tooltip.count():
                continue
            text = tooltip.first.inner_text(timeout=500).strip()
            if text and "validación" in text.casefold():
                return text
        except Exception:
            continue
    return None


def _merge_shared_details_into_messages(
    messages: list[PreviewMessage],
    shared_details: str,
) -> list[PreviewMessage]:
    call_stack = extract_call_stack_text(shared_details)
    detail_message = _extract_bc_dialog_message(shared_details)
    source, source_field = _extract_validation_source_fields(shared_details)
    merged: list[PreviewMessage] = []
    applied = False
    for message in messages:
        if not applied and message.context == "Validación de campo":
            merged.append(
                PreviewMessage(
                    message_type=message.message_type,
                    description=detail_message or message.description,
                    context=message.context,
                    context_field=message.context_field,
                    source=source or message.source,
                    source_field=source_field or message.source_field,
                    additional_information=shared_details.strip(),
                    call_stack=call_stack or message.call_stack,
                )
            )
            applied = True
            continue
        merged.append(message)
    if not applied:
        for index, message in enumerate(merged):
            if message.context != "Validación de página":
                continue
            merged[index] = PreviewMessage(
                message_type=message.message_type,
                description=detail_message or message.description,
                context=message.context,
                context_field=message.context_field,
                source=source or message.source,
                source_field=source_field or message.source_field,
                additional_information=shared_details.strip(),
                call_stack=call_stack or message.call_stack,
            )
            applied = True
            break
    if not applied:
        merged.append(
            PreviewMessage(
                message_type="Error",
                description=detail_message or shared_details.splitlines()[0],
                context="Validación de página",
                context_field=None,
                source=source,
                source_field=source_field,
                additional_information=shared_details.strip(),
                call_stack=call_stack,
            )
        )
    return merged


def _extract_field_validation_lines(body: str) -> tuple[str, ...]:
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line in _SKIP_DIALOG_LINES:
            continue
        lowered = line.casefold()
        if "ha revelado un problema en el campo" in lowered:
            lines.append(line)
        elif "validation" in lowered and "field" in lowered:
            lines.append(line)
    return tuple(dict.fromkeys(lines))


def _extract_validation_field_name(line: str) -> str | None:
    marker = "El campo de validación "
    if marker not in line:
        return None
    tail = line.split(marker, 1)[1]
    if " ha revelado un problema" in tail:
        return tail.split(" ha revelado un problema", 1)[0].strip()
    return None


def _extract_validation_target_field(line: str) -> str | None:
    marker = " ha revelado un problema en el campo "
    if marker not in line:
        return None
    return line.split(marker, 1)[1].rstrip(".").strip() or None


def _extract_validation_source_fields(
    shared_details: str,
) -> tuple[str | None, str | None]:
    for raw_line in shared_details.splitlines():
        line = raw_line.strip()
        if not line or line in _SKIP_DIALOG_LINES:
            continue
        if " ha revelado un problema en el campo " in line:
            _, tail = line.split(" ha revelado un problema en el campo ", 1)
            field_name = tail.rstrip(".").strip()
            if field_name:
                return None, field_name
        if " must have a value" in line.casefold():
            return line.split(" must have a value", 1)[0].strip(), None
        if " debe tener un valor" in line.casefold():
            return line.split(" debe tener un valor", 1)[0].strip(), None
    return None, None


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:80] or "item"


def _css_string(value: str | None) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _optional_attribute(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _confirmation_visible(
    body_text: str,
    confirmation_markers: tuple[str, ...],
) -> bool:
    return any(marker in body_text for marker in confirmation_markers)


_SHARE_DETAILS_LABELS = ("Compartir detalles", "Share details")
_COPY_ERROR_DETAILS_LABELS = (
    "Copiar detalles del error",
    "Copy error details",
)
_VALIDATION_POPOVER_MARKERS = (
    "ha revelado un problema en el campo",
    "revealed a problem in the field",
)

_SKIP_DIALOG_LINES = frozenset(
    {
        "Aceptar",
        "Cancelar",
        "Sí",
        "No",
        "OK",
        "Compartir detalles",
        "Share details",
        "Copiar detalles del error",
        "Copy error details",
        "Compartir detalles mediante Teams",
        "Share details in Teams",
        "Compartir detalles por correo electrónico",
        "Share details by email",
    }
)


def _extract_bc_dialog_message(dialog_text: str) -> str | None:
    validation_lines = _extract_field_validation_lines(dialog_text)
    if validation_lines:
        return validation_lines[0]

    message_label = "mensaje de error:"
    for raw_line in dialog_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.casefold()
        if lowered.startswith(message_label):
            inline = line.split(":", 1)[1].strip()
            if inline:
                return inline
            continue
        if line in _SKIP_DIALOG_LINES:
            continue
        if line.startswith("¿Le resultó útil"):
            break
        if extract_call_stack_text(line):
            break
        if _is_bc_support_metadata_line(line):
            continue
        if _looks_like_bc_session_id_line(line):
            continue
        return line

    lines: list[str] = []
    pending_error_message = False
    for raw_line in dialog_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.casefold()
        if lowered.startswith(message_label):
            inline = line.split(":", 1)[1].strip()
            if inline:
                return inline
            pending_error_message = True
            continue
        if pending_error_message:
            if _is_bc_support_metadata_line(line) or _looks_like_bc_session_id_line(
                line
            ):
                pending_error_message = False
                continue
            return line
        if line in _SKIP_DIALOG_LINES:
            continue
        if line.startswith("¿Le resultó útil"):
            break
        if extract_call_stack_text(line):
            break
        if _is_bc_support_metadata_line(line) or _looks_like_bc_session_id_line(
            line
        ):
            continue
        lines.append(line)
    return lines[0] if lines else None


def _is_bc_support_metadata_line(line: str) -> bool:
    lowered = line.casefold()
    return (
        lowered.startswith("si solicita soporte")
        or lowered.startswith("if you request support")
        or lowered.startswith("id. sesión")
        or lowered.startswith("session id")
        or lowered.startswith("pila de llamadas")
        or lowered.startswith("call stack")
        or lowered.startswith("id. de sesión")
    )


def _looks_like_bc_session_id_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        stripped,
        flags=re.IGNORECASE,
    ):
        return True
    return stripped.isdigit() and len(stripped) >= 8


def _extract_bc_dialog_details(dialog_text: str) -> str | None:
    call_stack = extract_call_stack_text(dialog_text)
    if call_stack:
        return call_stack
    detail_lines: list[str] = []
    for raw_line in dialog_text.splitlines():
        line = raw_line.strip()
        if not line or line in _SKIP_DIALOG_LINES:
            continue
        if line.startswith("¿Le resultó útil"):
            break
        if extract_call_stack_text(line):
            detail_lines.append(line)
            continue
        if detail_lines:
            detail_lines.append(line)
    return "\n".join(detail_lines) if detail_lines else None


def _find_validation_popover(frame: Frame) -> Locator | None:
    for candidate_frame in frame.page.frames:
        popover = _find_validation_popover_in_frame(candidate_frame)
        if popover is not None:
            return popover
    return None


def _find_validation_popover_in_frame(frame: Frame) -> Locator | None:
    for selector in (
        '[class*="validationerror-tooltip"]',
        '[class*="validationerror-browsersideactions"]',
        '[class*="validationerror"]',
    ):
        tooltips = frame.locator(selector)
        for index in range(min(tooltips.count(), 10)):
            node = tooltips.nth(index)
            try:
                if not node.is_visible():
                    continue
                text = node.inner_text(timeout=500).casefold()
                if not any(marker in text for marker in _VALIDATION_POPOVER_MARKERS):
                    continue
                actions = node.locator(
                    'a[role="button"], button, [role="button"]'
                ).count()
                if actions >= 1:
                    return node
            except Exception:
                continue
    best: Locator | None = None
    best_score = 10_000
    for marker_text in _VALIDATION_POPOVER_MARKERS:
        marker = frame.get_by_text(marker_text, exact=False)
        for index in range(min(marker.count(), 8)):
            node = marker.nth(index)
            try:
                if not node.is_visible():
                    continue
            except Exception:
                continue
            for level in range(1, 10):
                container = node.locator(f"xpath=ancestor::div[{level}]")
                try:
                    if not container.count():
                        continue
                    text = container.inner_text(timeout=500).strip()
                    action_count = container.locator(
                        'a[role="button"]:visible, button:visible, [role="button"]:visible'
                    ).count()
                    if marker_text not in text.casefold():
                        continue
                    if action_count < 1 or action_count > 5:
                        continue
                    if len(text) > 400:
                        continue
                    score = len(text) + action_count * 50
                    if score < best_score:
                        best = container
                        best_score = score
                except Exception:
                    continue
    return best


def _open_validation_popover(frame: Frame) -> Locator | None:
    popover = _find_validation_popover(frame)
    if popover is not None:
        return popover
    for control_name in ("Estado Contrato",):
        container = frame.locator(f'[controlname="{_css_string(control_name)}"]')
        try:
            if not container.count():
                continue
            container.first.scroll_into_view_if_needed(timeout=2_000)
            for selector in (
                '[class*="validation"]',
                '[class*="error-icon"]',
                '[class*="status-error"]',
                '.edit-container [class*="error"]',
                '.edit-container button',
            ):
                icon = container.locator(selector)
                try:
                    if icon.count() and icon.first.is_visible():
                        icon.first.click(timeout=1_000)
                        frame.page.wait_for_timeout(700)
                        popover = _find_validation_popover(frame)
                        if popover is not None:
                            return popover
                except Exception:
                    continue
            box = container.first.bounding_box()
            if box:
                for offset in (18, 28, 36):
                    frame.page.mouse.click(
                        box["x"] + min(offset, box["width"] * 0.15),
                        box["y"] + box["height"] / 2,
                    )
                    frame.page.wait_for_timeout(700)
                    popover = _find_validation_popover(frame)
                    if popover is not None:
                        return popover
        except Exception:
            continue
    return None


def _click_popover_share_button(frame: Frame, popover: Locator) -> bool:
    for label in _SHARE_DETAILS_LABELS:
        for locator in (
            popover.locator(f'a[role="button"][title*="{_css_string(label)}" i]'),
            popover.locator(f'a[role="button"][aria-label*="{_css_string(label)}" i]'),
            popover.locator(f'button[title*="{_css_string(label)}" i]'),
            popover.locator(f'button[aria-label*="{_css_string(label)}" i]'),
            popover.get_by_role("button", name=label),
        ):
            try:
                if not locator.count():
                    continue
                candidate = locator.last
                if not candidate.is_visible():
                    continue
                candidate.click(timeout=2_000)
                frame.page.wait_for_timeout(400)
                return True
            except Exception:
                continue
    actions = popover.locator(
        'a[role="button"]:visible, button:visible, [role="button"]:visible'
    )
    try:
        count = actions.count()
    except Exception:
        return False
    if count >= 2:
        try:
            actions.nth(count - 1).click(timeout=2_000)
            frame.page.wait_for_timeout(400)
            return True
        except Exception:
            return False
    return False


def _has_share_details_control(dialog: Locator, frame: Frame) -> bool:
    for label in _SHARE_DETAILS_LABELS:
        for scope in (dialog, frame.locator("body")):
            for locator in (
                scope.get_by_role("button", name=label),
                scope.get_by_text(label, exact=True),
                scope.locator(f'button[title*="{_css_string(label)}" i]'),
                scope.locator(f'button[aria-label*="{_css_string(label)}" i]'),
            ):
                try:
                    if locator.count() and locator.first.is_visible():
                        return True
                except Exception:
                    continue
    return False


def _legacy_invoice_configuration(
    document: DocumentReference,
) -> tuple[DocumentTypeDefinition, ActionDefinition]:
    sales = document.kind in {"sales", "sales_invoice"}
    action = ActionDefinition(
        id="preview_posting",
        label="Vista previa de registro",
        safety="diagnostic",
        menu_aria_label="Acciones relacionadas para Registrar",
        action_aria_label="Vista previa de registro",
        result_markers=("Mensajes de error", "Vista previa de registro"),
        parse_error_rows=True,
    )
    definition = DocumentTypeDefinition(
        id="sales_invoice" if sales else "purchase_invoice",
        label="Factura de venta" if sales else "Factura de compra",
        page_id=43 if sales else 51,
        source_table="Sales Header" if sales else "Purchase Header",
        odata_service="salesDocuments" if sales else "purchaseDocuments",
        odata_key_field="number",
        page_filters={"Document Type": "Invoice"},
        actions=(action,),
    )
    return definition, action
