"""Expandir sección y editar Estado."""
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

    show_more = frame.locator('button[title*="Mostrar más" i], button[aria-label*="Mostrar más" i]')
    print("show more buttons", show_more.count())
    for i in range(show_more.count()):
        btn = show_more.nth(i)
        if btn.is_visible():
            print("click", btn.get_attribute("aria-label"), btn.get_attribute("title"))
            btn.click()
            page.wait_for_timeout(800)

    container = frame.locator('[controlname="Estado Contrato"]')
    container.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    print("visible", container.is_visible(), "class", container.get_attribute("class"))

    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(1500)
    container = frame.locator('[controlname="Estado Contrato"]')
    print("after edit class", container.get_attribute("class"))
    val = container.locator('[role="textbox"]').first
    val.scroll_into_view_if_needed()
    val.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(1000)
    opts = frame.get_by_role("option")
    print("options", opts.count())
    for i in range(min(opts.count(), 12)):
        print(i, opts.nth(i).inner_text(timeout=300))

    page.wait_for_timeout(3000)
    browser.close()
