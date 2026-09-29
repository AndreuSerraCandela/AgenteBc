"""Conexión BC embebida en el skill (OData, web, empresa)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agentebc.config import Settings
from typing import Protocol


class _SkillLike(Protocol):
    spec: object
    connection: SkillConnection | None


@dataclass(frozen=True, slots=True)
class SkillConnection:
    odata_base_url: str | None = None
    web_base_url: str | None = None
    company: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SkillConnection | None:
        if not value or not isinstance(value, dict):
            return None
        odata = _optional_str(value.get("odata_base_url"))
        web = _optional_str(value.get("web_base_url"))
        company = _optional_str(value.get("company"))
        if not any((odata, web, company)):
            return None
        return cls(odata_base_url=odata, web_base_url=web, company=company)

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.odata_base_url:
            payload["odata_base_url"] = self.odata_base_url
        if self.web_base_url:
            payload["web_base_url"] = self.web_base_url
        if self.company:
            payload["company"] = self.company
        return payload


def resolve_skill_company(skill: _SkillLike, *, override: str = "") -> str:
    chosen = override.strip()
    if chosen:
        return chosen
    from_spec = (skill.spec.company or "").strip()
    if from_spec:
        return from_spec
    if skill.connection and skill.connection.company:
        return skill.connection.company.strip()
    return ""


def settings_for_skill(base: Settings, skill: _SkillLike) -> Settings:
    conn = skill.connection
    if conn is None:
        return base
    updates: dict[str, Any] = {}
    if conn.odata_base_url:
        updates["odata_base_url"] = conn.odata_base_url.rstrip("/")
    if conn.web_base_url:
        updates["web_base_url"] = conn.web_base_url.rstrip("/")
    if conn.company and not base.company:
        updates["company"] = conn.company
    if not updates:
        return base
    return replace(base, **updates)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
