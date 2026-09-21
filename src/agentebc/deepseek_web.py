from __future__ import annotations

import threading
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError, sync_playwright

from .ai_web_cdp import AiWebCdpError, ensure_ai_web_cdp_ready
from .browser import launch_persistent_context
from .config import Settings

_CDP_HINT = (
    "DeepSeek bloquea el login en navegadores automatizados. Opciones: "
    "1) usa AGENTEBC_AI_PROVIDER=deepseek con API key; "
    "2) abre Chrome manualmente con depuración remota y configura "
    "AGENTEBC_DEEPSEEK_WEB_CDP_URL=http://127.0.0.1:9222"
)

_DEEPSEEK_WEB_LOCK = threading.Lock()
_CDP_LOGIN_WAIT_SECONDS = 30.0

_CHAT_INPUT_SELECTORS = (
    "textarea[placeholder='Message DeepSeek']",
    "#chat-input",
    "textarea[data-testid='chat-input']",
    "textarea",
    "[contenteditable='true'][role='textbox']",
    "[contenteditable='true']",
)

_SIGN_IN_SELECTORS = (
    ".ds-sign-in-form__main",
    ".ds-sign-in-form-wrapper",
    "input[type='password']",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "button:has-text('Iniciar sesión')",
)

_NEW_CHAT_SELECTORS = (
    "a[href='/']",
    "button[aria-label*='New']",
    "button[aria-label*='Nuevo']",
    "button:has-text('新对话')",
    "button:has-text('Nuevo chat')",
)


class DeepSeekWebError(RuntimeError):
    """Error al consultar chat.deepseek.com con Playwright."""


class DeepSeekWebClient:
    def __init__(
        self,
        *,
        chat_url: str,
        profile_dir: Path,
        settings: Settings,
        timeout_seconds: float,
        login_timeout_seconds: float,
        cdp_url: str | None = None,
    ) -> None:
        self._chat_url = chat_url.rstrip("/")
        self._profile_dir = profile_dir
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._login_timeout_seconds = login_timeout_seconds
        self._cdp_url = cdp_url.rstrip("/") if cdp_url else None

    @property
    def model(self) -> str:
        return "deepseek-web"

    @property
    def provider(self) -> str:
        return "deepseek_web"

    @property
    def chat_url(self) -> str:
        return self._chat_url

    @property
    def external_label(self) -> str:
        return "DeepSeek"

    @property
    def cdp_available(self) -> bool:
        return bool(self._cdp_url)

    def focus_chat_tab(self) -> None:
        if not self._cdp_url:
            raise DeepSeekWebError(
                "Para ir a la pestaña existente configura "
                "AGENTEBC_DEEPSEEK_WEB_CDP_URL"
            )
        if not _DEEPSEEK_WEB_LOCK.acquire(blocking=False):
            raise DeepSeekWebError(
                "Ya hay otra consulta a DeepSeek web en ejecución"
            )
        try:
            self._ensure_cdp_ready()
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(self._cdp_url)
                except Exception as exc:
                    raise DeepSeekWebError(
                        f"No se pudo conectar a Chrome en {self._cdp_url}. "
                        f"Detalle: {exc}"
                    ) from exc
                try:
                    if not browser.contexts:
                        raise DeepSeekWebError("No hay pestañas abiertas en Chrome")
                    page = self._pick_page(browser.contexts[0])
                    page.bring_to_front()
                finally:
                    browser.close()
        finally:
            _DEEPSEEK_WEB_LOCK.release()

    def submit_prompt_only(
        self,
        user_prompt: str,
        system_prompt: str = "",
    ) -> None:
        prompt = _merge_prompts(system_prompt, user_prompt)
        if not _DEEPSEEK_WEB_LOCK.acquire(blocking=False):
            raise DeepSeekWebError(
                "Ya hay otra consulta a DeepSeek web en ejecución"
            )
        try:
            self._submit_locked(prompt)
        finally:
            _DEEPSEEK_WEB_LOCK.release()

    def _ensure_cdp_ready(self) -> None:
        if not self._cdp_url:
            return
        try:
            ensure_ai_web_cdp_ready(self._cdp_url, self._chat_url)
        except AiWebCdpError as exc:
            raise DeepSeekWebError(str(exc)) from exc

    def _submit_locked(self, prompt: str) -> None:
        with sync_playwright() as playwright:
            browser: Browser | None = None
            context: BrowserContext
            owns_context = False
            if self._cdp_url:
                self._ensure_cdp_ready()
                try:
                    browser = playwright.chromium.connect_over_cdp(self._cdp_url)
                except Exception as exc:
                    raise DeepSeekWebError(
                        f"No se pudo conectar a Chrome en {self._cdp_url}. "
                        "Ábrelo manualmente con --remote-debugging-port=9222. "
                        f"Detalle: {exc}"
                    ) from exc
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 1000}
                    )
            else:
                self._profile_dir.mkdir(parents=True, exist_ok=True)
                context = launch_persistent_context(
                    playwright,
                    self._settings,
                    user_data_dir=str(self._profile_dir),
                    viewport={"width": 1440, "height": 1000},
                )
                owns_context = True
            try:
                page = self._pick_page(context)
                page.bring_to_front()
                page.set_default_timeout(int(self._timeout_seconds * 1000))
                if "deepseek.com" not in page.url:
                    page.goto(
                        self._chat_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._timeout_seconds * 1000),
                    )
                self._wait_until_ready(page)
                if not self._cdp_url:
                    self._start_new_chat(page)
                self._submit_prompt(page, prompt)
            finally:
                if owns_context:
                    context.close()
                elif browser is not None:
                    browser.close()

    def _pick_page(self, context: BrowserContext) -> Page:
        deepseek_pages = [
            page for page in context.pages if "deepseek.com" in page.url
        ]
        if deepseek_pages:
            for page in deepseek_pages:
                if self._chat_input_visible(page):
                    return page
            return deepseek_pages[0]
        page = context.new_page()
        return page

    def _wait_until_ready(self, page: Page) -> None:
        if self._chat_input_visible(page):
            return
        if self._settings.browser_headless and self._is_sign_in_visible(page):
            raise DeepSeekWebError(
                "DeepSeek web requiere iniciar sesión. Pon "
                "AGENTEBC_BROWSER_HEADLESS=false, reinicia AgenteBc y "
                f"entra en {self._chat_url} con el navegador que se abra."
            )

        login_wait = (
            min(self._login_timeout_seconds, _CDP_LOGIN_WAIT_SECONDS)
            if self._cdp_url
            else self._login_timeout_seconds
        )
        deadline = time.monotonic() + login_wait
        while time.monotonic() < deadline:
            if self._chat_input_visible(page):
                return
            page.wait_for_timeout(1_000)

        raise DeepSeekWebError(
            "No se detectó sesión en DeepSeek tras "
            f"{int(self._login_timeout_seconds)} s. {_CDP_HINT}"
        )

    def _chat_input_visible(self, page: Page) -> bool:
        for selector in _CHAT_INPUT_SELECTORS:
            try:
                if page.locator(selector).first.is_visible(timeout=500):
                    return True
            except TimeoutError:
                continue
        return False

    def _is_sign_in_visible(self, page: Page) -> bool:
        for selector in _SIGN_IN_SELECTORS:
            try:
                if page.locator(selector).first.is_visible(timeout=1_000):
                    return True
            except TimeoutError:
                continue
        return False

    def _start_new_chat(self, page: Page) -> None:
        for selector in _NEW_CHAT_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1_000):
                    locator.click()
                    page.wait_for_timeout(800)
                    return
            except TimeoutError:
                continue

    def _submit_prompt(self, page: Page, prompt: str) -> None:
        textarea = self._chat_input(page)
        textarea.click()
        textarea.fill(prompt)
        textarea.press("Enter")
        send_button = page.locator(
            "button[aria-label='Send message'], "
            "button[aria-label='Enviar mensaje'], "
            "[data-testid='send-button']"
        ).first
        try:
            if send_button.is_visible(timeout=250) and send_button.is_enabled():
                send_button.click()
        except TimeoutError:
            pass

    def _chat_input(self, page: Page):
        for selector in _CHAT_INPUT_SELECTORS:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=2_000)
                return locator
            except TimeoutError:
                continue
        raise DeepSeekWebError(
            "No se encontró el cuadro de mensaje en chat.deepseek.com. "
            "Asegúrate de haber iniciado sesión y de ver el chat principal."
        )

def _merge_prompts(system_prompt: str, user_prompt: str) -> str:
    system = system_prompt.strip()
    user = user_prompt.strip()
    if system and user:
        return f"{system}\n\n{user}"
    return system or user
