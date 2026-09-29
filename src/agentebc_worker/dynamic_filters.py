from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

DynamicFilterId = Literal["current_month", "current_year", "month_to_today"]

DYNAMIC_FILTER_IDS: frozenset[str] = frozenset(
    {"current_month", "current_year", "month_to_today"}
)


@dataclass(frozen=True, slots=True)
class ResolvedDateRange:
    dynamic: str | None
    date_from: date
    date_to: date

    def as_dict(self) -> dict[str, str | None]:
        return {
            "dynamic": self.dynamic,
            "from": self.date_from.isoformat(),
            "to": self.date_to.isoformat(),
        }


def resolve_dynamic_filter(
    dynamic: str,
    *,
    reference: date | None = None,
) -> ResolvedDateRange:
    ref = reference or date.today()
    if dynamic not in DYNAMIC_FILTER_IDS:
        raise ValueError(
            f"Filtro dinámico desconocido: {dynamic!r}. "
            f"Válidos: {', '.join(sorted(DYNAMIC_FILTER_IDS))}"
        )
    start, end = _RESOLVERS[dynamic](ref)
    return ResolvedDateRange(dynamic=dynamic, date_from=start, date_to=end)


def _current_month(ref: date) -> tuple[date, date]:
    last = calendar.monthrange(ref.year, ref.month)[1]
    return date(ref.year, ref.month, 1), date(ref.year, ref.month, last)


def _current_year(ref: date) -> tuple[date, date]:
    return date(ref.year, 1, 1), date(ref.year, 12, 31)


def _month_to_today(ref: date) -> tuple[date, date]:
    start, _ = _current_month(ref)
    return start, ref


_RESOLVERS: dict[str, Callable[[date], tuple[date, date]]] = {
    "current_month": _current_month,
    "current_year": _current_year,
    "month_to_today": _month_to_today,
}
