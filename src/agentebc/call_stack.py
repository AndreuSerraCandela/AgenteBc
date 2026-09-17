from __future__ import annotations

import re
from dataclasses import dataclass

STACK_FRAME_PATTERN = re.compile(
    r'"([^"]+)"\s*\((Codeunit|CodeUnit|PageExtension|Page|Table|Report)\s+(\d+)\)'
    r"\.([^\s]+)\s+line\s+(\d+)",
    re.IGNORECASE,
)
STACK_FRAME_PATTERN_UNQUOTED = re.compile(
    r"([A-Za-z0-9_]+)\s*\((Codeunit|CodeUnit|PageExtension|Page|Table|Report)\s+(\d+)\)"
    r"\.([^\s]+)\s+line\s+(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StackFrame:
    object_name: str
    object_type: str
    object_id: int
    procedure: str
    line: int


def _iter_stack_frame_matches(call_stack: str):
    seen: set[tuple[str, str, int, str, int]] = set()
    for pattern in (STACK_FRAME_PATTERN, STACK_FRAME_PATTERN_UNQUOTED):
        for match in pattern.finditer(call_stack):
            key = (
                match.group(1),
                match.group(2),
                int(match.group(3)),
                match.group(4),
                int(match.group(5)),
            )
            if key in seen:
                continue
            seen.add(key)
            yield match


def parse_call_stack_frames(call_stack: str) -> tuple[StackFrame, ...]:
    frames: list[StackFrame] = []
    for match in _iter_stack_frame_matches(call_stack):
        frames.append(
            StackFrame(
                object_name=match.group(1),
                object_type=match.group(2),
                object_id=int(match.group(3)),
                procedure=match.group(4),
                line=int(match.group(5)),
            )
        )
    return tuple(frames)


def extract_call_stack_text(text: str) -> str | None:
    if not text.strip():
        return None

    frames = parse_call_stack_frames(text)
    if frames:
        stack_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if (
                STACK_FRAME_PATTERN.search(line)
                or STACK_FRAME_PATTERN_UNQUOTED.search(line)
            ):
                stack_lines.append(line)
            elif stack_lines and line.startswith('"'):
                stack_lines.append(line)
        if stack_lines:
            return "\n".join(stack_lines)
        return text.strip()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if STACK_FRAME_PATTERN.search(line) or STACK_FRAME_PATTERN_UNQUOTED.search(
            line
        ):
            return line
    return None
