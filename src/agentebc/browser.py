from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Playwright

    from .config import Settings

_ALLOWED_BROWSER_CHANNELS = {
    "chrome",
    "msedge",
    "chrome-beta",
    "msedge-beta",
    "chromium",
}


def launch_browser(playwright: Playwright, settings: Settings) -> Browser:
    kwargs = _browser_kwargs(settings)
    try:
        return playwright.chromium.launch(**kwargs)
    except Exception:
        if "channel" not in kwargs:
            raise
        fallback = dict(kwargs)
        fallback.pop("channel")
        return playwright.chromium.launch(**fallback)


def launch_persistent_context(
    playwright: Playwright,
    settings: Settings,
    *,
    user_data_dir: str,
    **extra: Any,
) -> BrowserContext:
    kwargs = _browser_kwargs(settings, user_data_dir=user_data_dir, **extra)
    try:
        return playwright.chromium.launch_persistent_context(**kwargs)
    except Exception:
        if "channel" not in kwargs:
            raise
        fallback = dict(kwargs)
        fallback.pop("channel")
        return playwright.chromium.launch_persistent_context(**fallback)


def _browser_kwargs(settings: Settings, **extra: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headless": settings.browser_headless,
        **extra,
    }
    if settings.browser_channel and settings.browser_channel != "chromium":
        kwargs["channel"] = settings.browser_channel
    return kwargs


def normalize_browser_channel(value: str | None) -> str | None:
    if value is None:
        return "msedge"
    normalized = value.strip().lower()
    if not normalized:
        return "msedge"
    if normalized not in _ALLOWED_BROWSER_CHANNELS:
        allowed = ", ".join(sorted(_ALLOWED_BROWSER_CHANNELS))
        raise ValueError(
            f"AGENTEBC_BROWSER_CHANNEL debe ser uno de: {allowed}"
        )
    return normalized
