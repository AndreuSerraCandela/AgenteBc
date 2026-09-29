"""Detalle de errores de vista previa BC para informes del worker."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agentebc.web_preview import PreviewMessage, PreviewResult


def error_detail_from_preview(result: PreviewResult) -> dict[str, Any]:
    return {
        "web_outcome": result.outcome,
        "title": result.title,
        "messages": [asdict(message) for message in result.messages],
        "raw_rows": list(result.raw_rows),
        "screenshot_path": (
            str(result.screenshot_path) if result.screenshot_path else None
        ),
    }


def error_detail_from_exception(message: str, *, web_outcome: str | None = None) -> dict[str, Any]:
    return {
        "web_outcome": web_outcome or "exception",
        "title": "",
        "messages": [
            {
                "message_type": "exception",
                "description": message,
                "context": None,
                "context_field": None,
                "source": None,
                "source_field": None,
                "additional_information": None,
                "call_stack": None,
            }
        ],
        "raw_rows": [],
        "screenshot_path": None,
    }


def format_error_detail_text(detail: dict[str, Any] | None) -> str:
    if not detail:
        return ""
    lines: list[str] = []
    outcome = detail.get("web_outcome")
    if outcome:
        lines.append(f"Resultado acción web: {outcome}")
    title = detail.get("title")
    if title:
        lines.append(f"Título ficha: {title}")
    messages = detail.get("messages") or []
    if messages:
        lines.append("")
        lines.append("Mensajes de error (BC):")
        for index, raw in enumerate(messages, start=1):
            if not isinstance(raw, dict):
                continue
            lines.extend(_format_message_lines(raw, index))
    raw_rows = detail.get("raw_rows") or []
    if raw_rows:
        lines.append("")
        lines.append("Filas crudas del cuadro de errores BC:")
        for row in raw_rows:
            lines.append(f"  {row}")
    screenshot = detail.get("screenshot_path")
    if screenshot:
        lines.append("")
        lines.append(f"Captura: {screenshot}")
    return "\n".join(lines).strip()


def preview_message_from_dict(data: dict[str, Any]) -> PreviewMessage:
    return PreviewMessage(
        message_type=str(data.get("message_type") or ""),
        description=str(data.get("description") or ""),
        context=data.get("context"),
        context_field=data.get("context_field"),
        source=data.get("source"),
        source_field=data.get("source_field"),
        additional_information=data.get("additional_information"),
        call_stack=data.get("call_stack"),
    )


def _format_message_lines(message: dict[str, Any], index: int) -> list[str]:
    header = f"--- Mensaje {index}"
    msg_type = message.get("message_type")
    if msg_type:
        header += f" ({msg_type})"
    header += " ---"
    block = [header, f"  Descripción: {message.get('description') or '—'}"]
    for label, key in (
        ("Contexto", "context"),
        ("Campo contexto", "context_field"),
        ("Origen", "source"),
        ("Campo origen", "source_field"),
    ):
        value = message.get(key)
        if value:
            block.append(f"  {label}: {value}")
    extra = message.get("additional_information")
    if extra:
        block.append("  Información adicional:")
        for line in str(extra).splitlines():
            block.append(f"    {line}")
    stack = message.get("call_stack")
    if stack:
        block.append("  Pila de llamadas:")
        for line in str(stack).splitlines():
            block.append(f"    {line}")
    block.append("")
    return block
