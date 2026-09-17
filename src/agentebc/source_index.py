from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .call_stack import StackFrame, parse_call_stack_frames
from .models import SourceMatch

SUPPORTED_SUFFIXES = {".al", ".cal", ".txt"}
IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    ".pytest_cache",
    "node_modules",
    "bin",
    "obj",
}
OBJECT_HEADER_PATTERN = re.compile(
    r"^\s*(codeunit|pageextension|page|table|report)\s+(\d+)\b",
    re.IGNORECASE | re.MULTILINE,
)


class SourceIndex:
    """Búsqueda local y determinista sobre fuentes AL/C-AL."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError(f"No existe el directorio de fuentes: {self.root}")
        self.allowed_roots = tuple(
            root.resolve() for root in (allowed_roots or ())
        )

    def search(self, text: str, *, limit: int = 10) -> list[SourceMatch]:
        terms = _significant_terms(text)
        normalized_query = _normalize(text)
        if not normalized_query:
            return []

        matches: list[SourceMatch] = []
        for path in self._source_files():
            content = _read_text(path)
            if content is None:
                continue
            lines = content.splitlines()
            normalized_content = _normalize(content)
            if not any(term in normalized_content for term in terms):
                continue

            for index, line in enumerate(lines):
                normalized_line = _normalize(line)
                score = _score(normalized_query, normalized_line, terms)
                if score <= 0:
                    continue
                start = max(0, index - 2)
                end = min(len(lines), index + 3)
                excerpt = "\n".join(
                    f"{line_number + 1}: {lines[line_number]}"
                    for line_number in range(start, end)
                )
                matches.append(
                    SourceMatch(
                        path=str(path.relative_to(self.root)),
                        line=index + 1,
                        excerpt=excerpt,
                        score=score,
                    )
                )

        matches.sort(key=lambda item: (-item.score, item.path, item.line))
        return matches[:limit]

    def search_call_stack(
        self,
        call_stack: str,
        *,
        limit: int = 5,
    ) -> list[SourceMatch]:
        frames = parse_call_stack_frames(call_stack)
        if not frames:
            return []

        for index, frame in enumerate(frames):
            frame_weight = float(len(frames) - index)
            matches = self._matches_for_stack_frame(
                frame,
                frame_weight=frame_weight,
            )
            if not matches:
                continue
            return self._deduplicate_matches(matches)[:limit]
        return []

    def search_event_subscribers(
        self,
        frame: StackFrame,
        *,
        limit: int = 5,
    ) -> list[SourceMatch]:
        patterns = _event_subscriber_patterns(frame)
        if not patterns:
            return []

        matches: list[SourceMatch] = []
        for path in self._source_files():
            content = _read_text(path)
            if content is None:
                continue
            lines = content.splitlines()
            for index, line in enumerate(lines):
                if not any(pattern.search(line) for pattern in patterns):
                    continue
                start = max(0, index - 1)
                end = min(len(lines), index + 2)
                excerpt = "\n".join(
                    f"{number + 1}: {lines[number]}"
                    for number in range(start, end)
                )
                matches.append(
                    SourceMatch(
                        path=str(path.relative_to(self.root)),
                        line=index + 1,
                        excerpt=excerpt,
                        score=2.0,
                    )
                )

        matches.sort(key=lambda item: (-item.score, item.path, item.line))
        return self._deduplicate_matches(matches)[:limit]

    @staticmethod
    def _deduplicate_matches(matches: list[SourceMatch]) -> list[SourceMatch]:
        deduplicated: dict[tuple[str, int], SourceMatch] = {}
        for match in matches:
            key = (match.path, match.line)
            current = deduplicated.get(key)
            if current is None or match.score > current.score:
                deduplicated[key] = match
        return sorted(
            deduplicated.values(),
            key=lambda item: (-item.score, item.path, item.line),
        )

    def _matches_for_stack_frame(
        self,
        frame: StackFrame,
        *,
        frame_weight: float = 1.0,
    ) -> list[SourceMatch]:
        matches: list[SourceMatch] = []
        procedure_pattern = re.compile(
            rf"\b{re.escape(frame.procedure)}\b",
            re.IGNORECASE,
        )

        for path in self._source_files():
            content = _read_text(path)
            if content is None:
                continue
            if not _file_matches_stack_object(path, content, frame):
                continue

            lines = content.splitlines()
            procedure_line = _find_procedure_line(lines, frame.procedure)
            target_lines = _resolved_target_lines(
                frame,
                procedure_line,
                line_count=len(lines),
            )

            for index, line in enumerate(lines):
                line_number = index + 1
                score = _stack_line_score(
                    line_number=line_number,
                    line=line,
                    target_lines=target_lines,
                    procedure_pattern=procedure_pattern,
                )
                if score <= 0:
                    continue
                score = round(score * frame_weight, 4)
                start = max(0, index - 2)
                end = min(len(lines), index + 3)
                excerpt = "\n".join(
                    f"{number + 1}: {lines[number]}"
                    for number in range(start, end)
                )
                matches.append(
                    SourceMatch(
                        path=str(path.relative_to(self.root)),
                        line=line_number,
                        excerpt=excerpt,
                        score=score,
                    )
                )
        return matches

    def _source_files(self):
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if any(part.lower() in IGNORED_DIRECTORIES for part in path.parts):
                continue
            if self.allowed_roots and not _is_within_allowed_roots(
                path,
                self.allowed_roots,
            ):
                continue
            yield path


def _is_within_allowed_roots(path: Path, allowed_roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _read_text(path: Path) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _object_key(value: str) -> str:
    folded = unicodedata.normalize("NFD", value.casefold())
    stripped = "".join(
        character
        for character in folded
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]", "", stripped)


def _normalize_object_type(value: str) -> str:
    return _object_key(value)


def _file_matches_stack_object(path: Path, content: str, frame: StackFrame) -> bool:
    frame_key = _object_key(frame.object_name)
    expected_type = _normalize_object_type(frame.object_type)
    header = content[:8000]

    for match in OBJECT_HEADER_PATTERN.finditer(header):
        if int(match.group(2)) != frame.object_id:
            continue
        if _normalize_object_type(match.group(1)) != expected_type:
            continue
        if _object_name_in_declaration(
            header,
            object_type=match.group(1),
            object_id=frame.object_id,
            frame_key=frame_key,
        ):
            return True
    return False


def _object_name_in_declaration(
    header: str,
    *,
    object_type: str,
    object_id: int,
    frame_key: str,
) -> bool:
    quoted = re.search(
        rf"{object_type}\s+{object_id}\s+\"([^\"]+)\"",
        header,
        re.IGNORECASE,
    )
    if quoted is not None and _object_key(quoted.group(1)) == frame_key:
        return True

    unquoted = re.search(
        rf"{object_type}\s+{object_id}\s+([\w]+)",
        header,
        re.IGNORECASE,
    )
    if unquoted is not None and _object_key(unquoted.group(1)) == frame_key:
        return True
    return False


def _event_subscriber_patterns(frame: StackFrame) -> tuple[re.Pattern[str], ...]:
    object_type = _normalize_object_type(frame.object_type)
    escaped_name = re.escape(frame.object_name)
    patterns: list[re.Pattern[str]] = []
    if object_type == "codeunit":
        patterns.append(
            re.compile(
                rf"ObjectType::Codeunit,\s*Codeunit::\"{escaped_name}\"",
                re.IGNORECASE,
            )
        )
    elif object_type == "page":
        patterns.append(
            re.compile(
                rf"ObjectType::Page,\s*Page::\"{escaped_name}\"",
                re.IGNORECASE,
            )
        )
    elif object_type == "table":
        patterns.append(
            re.compile(
                rf"ObjectType::Table,\s*Table::\"{escaped_name}\"",
                re.IGNORECASE,
            )
        )
    return tuple(patterns)


def _find_procedure_line(lines: list[str], procedure: str) -> int | None:
    pattern = re.compile(
        rf"\bprocedure\s+{re.escape(procedure)}\b",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if pattern.search(line):
            return index + 1
    return None


def _resolved_target_lines(
    frame: StackFrame,
    procedure_line: int | None,
    *,
    line_count: int,
) -> set[int]:
    if procedure_line is not None:
        relative = procedure_line + frame.line
        if 1 <= relative <= line_count:
            return {relative - 1, relative, relative + 1}
    return {frame.line}


def _significant_terms(value: str) -> tuple[str, ...]:
    words = re.findall(r"[\wáéíóúüñ]{4,}", _normalize(value))
    return tuple(dict.fromkeys(words)) or (_normalize(value),)


def _score(query: str, line: str, terms: tuple[str, ...]) -> float:
    if query in line:
        return 1.0
    present = sum(term in line for term in terms)
    if not present:
        return 0.0
    return round(0.75 * present / len(terms), 4)


def _stack_line_score(
    *,
    line_number: int,
    line: str,
    target_lines: set[int],
    procedure_pattern: re.Pattern[str],
) -> float:
    if line_number in target_lines:
        bonus = 0.5 if "ERROR(" in line.upper() else 0.0
        return 4.0 + bonus
    if any(abs(line_number - target) <= 2 for target in target_lines):
        if "ERROR(" in line.upper() or procedure_pattern.search(line):
            return 2.5
    if procedure_pattern.search(line) and "procedure" in line.casefold():
        return 1.5
    return 0.0
