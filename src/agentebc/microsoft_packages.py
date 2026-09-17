from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .call_stack import StackFrame, parse_call_stack_frames
from .models import SourceMatch
from .source_index import (
    OBJECT_HEADER_PATTERN,
    _find_procedure_line,
    _normalize_object_type,
    _object_key,
    _resolved_target_lines,
    _stack_line_score,
)

MICROSOFT_PACKAGE_PREFIX = "microsoft_"
OBJECT_KEY_SEPARATOR = ":"
INDEX_VERSION = 1


@dataclass(frozen=True, slots=True)
class PackageObjectRef:
    package_name: str
    entry_path: str

    def display_path(self) -> str:
        return f"{self.package_name}!{self.entry_path}"


class MicrosoftPackageIndex:
    """Índice cacheado sobre paquetes .app de Microsoft sin descomprimirlos."""

    def __init__(
        self,
        packages_dir: Path,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self.packages_dir = packages_dir.resolve()
        if not self.packages_dir.is_dir():
            raise ValueError(
                f"No existe el directorio de paquetes Microsoft: {self.packages_dir}"
            )
        self.cache_dir = (cache_dir or _default_cache_dir()).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.cache_dir / "microsoft-app-index.json"
        self._objects: dict[str, PackageObjectRef] = {}
        self._package_stats: dict[str, dict[str, int]] = {}
        self._load_or_build_index()

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
            matches = self._matches_for_stack_frame(frame, frame_weight=frame_weight)
            if matches:
                return self._deduplicate_matches(matches)[:limit]
        return []

    def _matches_for_stack_frame(
        self,
        frame: StackFrame,
        *,
        frame_weight: float = 1.0,
    ) -> list[SourceMatch]:
        reference = self._resolve_object(frame)
        if reference is None:
            return []

        package_path = self.packages_dir / reference.package_name
        content = self._read_zip_entry(package_path, reference.entry_path)
        if content is None:
            return []

        lines = content.splitlines()
        procedure_pattern = re.compile(
            rf"\b{re.escape(frame.procedure)}\b",
            re.IGNORECASE,
        )
        procedure_line = _find_procedure_line(lines, frame.procedure)
        target_lines = _resolved_target_lines(
            frame,
            procedure_line,
            line_count=len(lines),
        )

        matches: list[SourceMatch] = []
        display_path = reference.display_path()
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
                    path=display_path,
                    line=line_number,
                    excerpt=excerpt,
                    score=score,
                )
            )
        return matches

    def _resolve_object(self, frame: StackFrame) -> PackageObjectRef | None:
        keys = _object_lookup_keys(frame)
        for key in keys:
            reference = self._objects.get(key)
            if reference is not None:
                return reference
        return None

    def _load_or_build_index(self) -> None:
        packages = self._discover_packages()
        if self._index_path.is_file() and self._load_index_if_current(packages):
            return
        self._build_index(packages)
        self._save_index(packages)

    def _discover_packages(self) -> dict[str, Path]:
        discovered: dict[str, Path] = {}
        for path in sorted(self.packages_dir.glob("*.app")):
            if not _is_microsoft_package(path):
                continue
            discovered[path.name] = path
        return discovered

    def _load_index_if_current(self, packages: dict[str, Path]) -> bool:
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if payload.get("version") != INDEX_VERSION:
            return False
        if payload.get("packages_dir") != str(self.packages_dir):
            return False

        stored_packages = payload.get("packages", {})
        if stored_packages != _package_fingerprints(packages):
            return False

        objects: dict[str, PackageObjectRef] = {}
        for key, value in payload.get("objects", {}).items():
            if not isinstance(value, dict):
                return False
            package_name = value.get("package")
            entry_path = value.get("entry")
            if not package_name or not entry_path:
                return False
            objects[key] = PackageObjectRef(
                package_name=package_name,
                entry_path=entry_path,
            )

        self._objects = objects
        self._package_stats = stored_packages
        return True

    def _build_index(self, packages: dict[str, Path]) -> None:
        objects: dict[str, PackageObjectRef] = {}
        for package_name, package_path in packages.items():
            with zipfile.ZipFile(package_path) as archive:
                for entry_name in archive.namelist():
                    if not entry_name.lower().endswith(".al"):
                        continue
                    header = self._read_zip_header(archive, entry_name)
                    if not header:
                        continue
                    for match in OBJECT_HEADER_PATTERN.finditer(header):
                        object_type = _normalize_object_type(match.group(1))
                        object_id = int(match.group(2))
                        object_name = _extract_object_name(
                            header,
                            object_type=match.group(1),
                            object_id=object_id,
                        )
                        if object_name is None:
                            continue
                        key = _make_object_key(object_type, object_id, object_name)
                        objects[key] = PackageObjectRef(
                            package_name=package_name,
                            entry_path=entry_name,
                        )
        self._objects = objects
        self._package_stats = _package_fingerprints(packages)

    def _save_index(self, packages: dict[str, Path]) -> None:
        payload = {
            "version": INDEX_VERSION,
            "packages_dir": str(self.packages_dir),
            "built_at": datetime.now(UTC).isoformat(),
            "packages": _package_fingerprints(packages),
            "objects": {
                key: {
                    "package": reference.package_name,
                    "entry": reference.entry_path,
                }
                for key, reference in sorted(self._objects.items())
            },
        }
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _read_zip_entry(package_path: Path, entry_path: str) -> str | None:
        try:
            with zipfile.ZipFile(package_path) as archive:
                return archive.read(entry_path).decode("utf-8", errors="ignore")
        except (OSError, KeyError, zipfile.BadZipFile):
            return None

    @staticmethod
    def _read_zip_header(archive: zipfile.ZipFile, entry_path: str) -> str:
        try:
            with archive.open(entry_path) as handle:
                data = handle.read(8192)
        except KeyError:
            return ""
        return data.decode("utf-8", errors="ignore")

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


def resolve_alpackages_path(
    source_path: Path | None,
    configured: Path | None,
) -> Path | None:
    if configured is not None:
        resolved = configured.expanduser().resolve()
        return resolved if resolved.is_dir() else None
    if source_path is None:
        return None
    for relative in ("Funciones/.alpackages", "funciones/.alpackages"):
        candidate = (source_path / relative).resolve()
        if candidate.is_dir():
            return candidate
    return None


def _default_cache_dir() -> Path:
    return Path(__file__).resolve().parents[2] / ".cache"


def _is_microsoft_package(path: Path) -> bool:
    return (
        path.suffix.lower() == ".app"
        and path.name.casefold().startswith(MICROSOFT_PACKAGE_PREFIX)
    )


def _package_fingerprints(packages: dict[str, Path]) -> dict[str, dict[str, int]]:
    fingerprints: dict[str, dict[str, int]] = {}
    for name, path in sorted(packages.items()):
        stat = path.stat()
        fingerprints[name] = {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    return fingerprints


def _make_object_key(object_type: str, object_id: int, object_name: str) -> str:
    return OBJECT_KEY_SEPARATOR.join(
        (
            object_type,
            str(object_id),
            _object_key(object_name),
        )
    )


def _object_lookup_keys(frame: StackFrame) -> tuple[str, ...]:
    object_type = _normalize_object_type(frame.object_type)
    keys = [
        _make_object_key(object_type, frame.object_id, frame.object_name),
    ]
    if object_type == "pageextension":
        keys.append(_make_object_key("page", frame.object_id, frame.object_name))
    return tuple(keys)


def _extract_object_name(
    header: str,
    *,
    object_type: str,
    object_id: int,
) -> str | None:
    quoted = re.search(
        rf"{object_type}\s+{object_id}\s+\"([^\"]+)\"",
        header,
        re.IGNORECASE,
    )
    if quoted is not None:
        return quoted.group(1)

    unquoted = re.search(
        rf"{object_type}\s+{object_id}\s+([\w]+)",
        header,
        re.IGNORECASE,
    )
    if unquoted is not None:
        return unquoted.group(1)
    return None
