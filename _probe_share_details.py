"""Inspeccionar Compartir detalles en error de validación de campo."""
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from agentebc.config import Settings

COMPANY = "Piscis Dos Tres Hache, S.L."
CONTRACT = "CTO02-P0001"
settings = Settings.from_environment()
base = settings.odata_base_url.rsplit("/ODataV4", 1)[0]
query = urlencode(
    {
        "company": COMPANY,
        "page": "50209",
        "filter": f"'Sales Header'.'No.' IS '{CONTRACT}' AND 'Sales Header'.'Document Type' IS 'Order'",
    }
)
url = f"{base}/?{query}"


def set_estado_firmado(frame, page):
    show_more = frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first
    if show_more.count() and show_more.is_visible():
        show_more.click(force=True)
        page.wait_for_timeout(800)
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(1500)
    container = frame.locator('[controlname="Estado Contrato"]')
    container.scroll_into_view_if_needed()
    container.locator('[role="textbox"]').first.click()
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(800)
    frame.get_by_role("option", name="Firmado").first.click()
    page.wait_for_timeout(2500)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=False)
    context = browser.new_context(viewport={"width": 1440, "height": 1200})
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    frame = page.frames[1]
    set_estado_firmado(frame, page)

    container = frame.locator('[controlname="Estado Contrato"]')
    print("container html snippet:", container.inner_html(timeout=3000)[:1200])

    for sel in (
        '[aria-invalid="true"]',
        '.validation-error',
        '[class*="validation"]',
        '[class*="error-icon"]',
        'button[title*="Compartir" i]',
        'button[aria-label*="Compartir" i]',
    ):
        loc = frame.locator(sel)
        print(sel, loc.count())

    share = frame.locator(
        'button[title*="Compartir detalles" i],'
        'button[aria-label*="Compartir detalles" i],'
        '[role="button"]:has-text("Compartir detalles")'
    )
    print("share total", share.count())
    for i in range(share.count()):
        b = share.nth(i)
        print(" share", i, "vis", b.is_visible(), "title", b.get_attribute("title"))

    # click error icon if present
    icon = container.locator('[class*="error"], [class*="invalid"], button').first
    if icon.count():
        try:
            icon.click(timeout=2000)
            page.wait_for_timeout(800)
        except Exception as exc:
            print("icon click failed", exc)

    body = frame.locator("body").inner_text(timeout=3000)
    for line in body.splitlines():
        if "comentario" in line.casefold() or "validación" in line.casefold():
            print("LINE:", line)

    if share.count():
        target = share.first
        if not target.is_visible():
            target = share.filter(has_text="Compartir").first
        target.click(force=True)
        page.wait_for_timeout(600)
        for label in ("Copiar detalles del error", "Copy error details"):
            item = frame.get_by_role("menuitem", name=label)
            if not item.count():
                item = page.get_by_role("menuitem", name=label)
            if item.count() and item.first.is_visible():
                item.first.click()
                page.wait_for_timeout(600)
                clip = page.evaluate("async () => await navigator.clipboard.readText()")
                print("CLIPBOARD:\n", (clip or "")[:3000])
                break

    page.wait_for_timeout(2000)
    browser.close()
