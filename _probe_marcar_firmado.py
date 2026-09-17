"""Probar acción Marcar Como Firmado."""
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from agentebc.config import Settings

settings = Settings.from_environment()
base = settings.odata_base_url.rsplit("/ODataV4", 1)[0]
query = urlencode(
    {
        "company": settings.company or "Malla Publicidad",
        "page": "50209",
        "filter": "'Sales Header'.'No.' IS 'CTO02-P0001' AND 'Sales Header'.'Document Type' IS 'Order'",
    }
)
url = f"{base}/?{query}"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=False)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    frame = page.frames[1]

    action = frame.get_by_role("button", name="Marcar Como Firmado")
    print("action count", action.count())
    if not action.count():
        action = frame.locator('button[title*="Marcar Como Firmado" i], button[aria-label*="Marcar Como Firmado" i]')
        print("by title", action.count())
    if action.count():
        action.first.scroll_into_view_if_needed()
        action.first.click()
        page.wait_for_timeout(3000)
        for line in frame.locator("body").inner_text(timeout=3000).splitlines():
            if any(x in line.casefold() for x in ("error", "debe tener", "errores", "comentario")):
                print("LINE:", line)

    page.wait_for_timeout(4000)
    browser.close()
