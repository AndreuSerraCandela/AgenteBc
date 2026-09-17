from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Incident:
    error_text: str
    document_number: str | None = None
    company: str | None = None
    user: str | None = None
    call_stack: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SourceMatch:
    path: str
    line: int
    excerpt: str
    score: float


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    description: str
    value: Any


@dataclass(frozen=True, slots=True)
class ProposedSolution:
    description: str
    verification: str
    risk: str = "Debe revisarla un operario antes de actuar"


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    incident: Incident
    summary: str
    confidence: str
    evidence: tuple[Evidence, ...]
    source_matches: tuple[SourceMatch, ...]
    proposed_solutions: tuple[ProposedSolution, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
