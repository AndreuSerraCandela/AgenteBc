from __future__ import annotations

import threading
from urllib.parse import quote_plus

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError, sync_playwright

from .ai_web_cdp import AiWebCdpError, ensure_ai_web_cdp_ready
from .config import Settings

_GOOGLE_AI_WEB_LOCK = threading.Lock()
_MAX_URL_PROMPT_CHARS = 1200

_CHAT_INPUT_SELECTORS = (
    "textarea[name='q']",
    "textarea[aria-label*='Buscar']",
    "textarea[aria-label*='Search']",
    "[role='combobox'][name='q']",
    "textarea",
)


class GoogleAiWebError(RuntimeError):
    """Error al consultar Google Modo IA con Playwright."""


class GoogleAiWebClient:
    def __init__(
        self,
        *,
        base_url: str,
        settings: Settings,
        timeout_seconds: float,
        cdp_url: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._cdp_url = cdp_url.rstrip("/") if cdp_url else None
        self._last_external_url = self._base_url

    @property
    def model(self) -> str:
        return "google-ai-mode"

    @property
    def provider(self) -> str:
        return "google_ai_web"

    @property
    def chat_url(self) -> str:
        return self._last_external_url

    @property
    def external_label(self) -> str:
        return "Google Modo IA"

    @property
    def cdp_available(self) -> bool:
        return bool(self._cdp_url)

    def focus_chat_tab(self) -> None:
        if not self._cdp_url:
            raise GoogleAiWebError(
                "Para ir a la pestaña existente configura "
                "AGENTEBC_AI_WEB_CDP_URL"
            )
        self._with_cdp(self._focus_page)

    def submit_prompt_only(
        self,
        user_prompt: str,
        system_prompt: str = "",
    ) -> None:
        prompt = _merge_prompts(system_prompt, user_prompt)
        if not _GOOGLE_AI_WEB_LOCK.acquire(blocking=False):
            raise GoogleAiWebError(
                "Ya hay otra consulta web de IA en ejecución"
            )
        try:
            self._with_cdp(lambda page: self._submit_prompt(page, prompt))
        finally:
            _GOOGLE_AI_WEB_LOCK.release()

    def _with_cdp(self, action) -> None:
        if not self._cdp_url:
            raise GoogleAiWebError(
                "Google Modo IA web requiere AGENTEBC_AI_WEB_CDP_URL. "
                "Abre Chrome con scripts\\abrir-chrome-deepseek.bat"
            )
        try:
            ensure_ai_web_cdp_ready(self._cdp_url, self._base_url)
        except AiWebCdpError as exc:
            raise GoogleAiWebError(str(exc)) from exc
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(self._cdp_url)
            except Exception as exc:
                raise GoogleAiWebError(
                    f"No se pudo conectar a Chrome en {self._cdp_url}. "
                    f"Detalle: {exc}"
                ) from exc
            try:
                if not browser.contexts:
                    raise GoogleAiWebError("No hay pestañas abiertas en Chrome")
                page = self._pick_page(browser.contexts[0])
                page.bring_to_front()
                page.set_default_timeout(int(self._timeout_seconds * 1000))
                action(page)
            finally:
                browser.close()

    def _focus_page(self, page: Page) -> None:
        if "google." not in page.url:
            page.goto(
                self._base_url,
                wait_until="domcontentloaded",
                timeout=int(self._timeout_seconds * 1000),
            )
        self._last_external_url = page.url

    def _pick_page(self, context: BrowserContext) -> Page:
        google_pages = [
            page
            for page in context.pages
            if "google." in page.url and self._is_ai_mode_url(page.url)
        ]
        if google_pages:
            return google_pages[-1]
        google_pages = [page for page in context.pages if "google." in page.url]
        if google_pages:
            return google_pages[-1]
        return context.new_page()

    def _submit_prompt(self, page: Page, prompt: str) -> None:
        if len(prompt) <= _MAX_URL_PROMPT_CHARS:
            target_url = (
                "https://www.google.com/search?"
                f"q={quote_plus(prompt)}&udm=50"
            )
            page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=int(self._timeout_seconds * 1000),
            )
            self._last_external_url = page.url
            return

        page.goto(
            self._base_url,
            wait_until="domcontentloaded",
            timeout=int(self._timeout_seconds * 1000),
        )
        textarea = self._chat_input(page)
        textarea.click()
        textarea.fill(prompt)
        textarea.press("Enter")
        page.wait_for_timeout(1_000)
        self._last_external_url = page.url

    def _chat_input(self, page: Page):
        for selector in _CHAT_INPUT_SELECTORS:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=2_000)
                return locator
            except TimeoutError:
                continue
        raise GoogleAiWebError(
            "No se encontró el cuadro de búsqueda de Google Modo IA. "
            "Inicia sesión en Google en Chrome y prueba de nuevo."
        )

    @staticmethod
    def _is_ai_mode_url(url: str) -> bool:
        lowered = url.lower()
        return "udm=50" in lowered or "/ai" in lowered


def _merge_prompts(system_prompt: str, user_prompt: str) -> str:
    system = system_prompt.strip()
    user = user_prompt.strip()
    if system and user:
        return f"{system}\n\n{user}"
    return system or user
