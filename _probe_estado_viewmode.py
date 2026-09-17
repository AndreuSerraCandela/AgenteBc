"""Editar Estado en modo vista (sin botón Editar)."""
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

    show_more = frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first
    if show_more.count() and show_more.is_visible():
        show_more.click()
        page.wait_for_timeout(800)

    container = frame.locator('[controlname="Estado Contrato"]')
    container.scroll_into_view_if_needed()
    print("class view mode:", container.get_attribute("class"))
    val = container.locator('[role="textbox"]').first
    val.click()
    page.wait_for_timeout(300)
    val.dblclick()
    page.wait_for_timeout(300)
    for key in ("F4", "Alt+ArrowDown", "ArrowDown"):
        page.keyboard.press(key)
        page.wait_for_timeout(600)
        n = frame.get_by_role("option").count()
        print(key, "options", n)
        if n:
            break

    opts = frame.get_by_role("option")
    for i in range(min(opts.count(), 12)):
        print(i, opts.nth(i).inner_text(timeout=300))
    firmado = frame.get_by_role("option", name="Firmado")
    if firmado.count():
        firmado.first.click()
        page.wait_for_timeout(2000)
        for line in frame.locator("body").inner_text(timeout=3000).splitlines():
            if any(x in line.casefold() for x in ("error", "debe tener", "errores")):
                print("LINE:", line)

    page.wait_for_timeout(3000)
    browser.close()
