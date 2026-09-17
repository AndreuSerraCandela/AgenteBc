"""Probar edición Estado con contrato real."""
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from agentebc.config import Settings

CONTRACT = "CTO06-03148"
settings = Settings.from_environment()
base = settings.odata_base_url.rsplit("/ODataV4", 1)[0]
query = urlencode(
    {
        "company": settings.company or "Malla Publicidad",
        "page": "50209",
        "filter": f"'Sales Header'.'No.' IS '{CONTRACT}' AND 'Sales Header'.'Document Type' IS 'Order'",
    }
)
url = f"{base}/?{query}"


def expand_general(frame, page):
    btn = frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first
    if btn.count() and btn.is_visible():
        btn.click()
        page.wait_for_timeout(600)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=False)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    frame = page.frames[1]
    expand_general(frame, page)

    container = frame.locator('[controlname="Estado Contrato"]')
    container.scroll_into_view_if_needed()
    print("BEFORE edit - class:", container.get_attribute("class"))
    val = container.locator('[role="textbox"]').first
    print("BEFORE value:", val.get_attribute("title") or val.inner_text(timeout=500))

    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2000)
    print("AFTER edit - class:", container.get_attribute("class"))
    val = container.locator('[role="textbox"]').first
    print("AFTER value:", val.get_attribute("title") or val.inner_text(timeout=500))

    val.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(1000)
    opts = frame.get_by_role("option")
    print("options:", opts.count())
    for i in range(min(opts.count(), 8)):
        print(" ", opts.nth(i).inner_text(timeout=300))

    firmado = frame.get_by_role("option", name="Firmado")
    if firmado.count() and firmado.first.is_visible():
        firmado.first.click()
        page.wait_for_timeout(2500)
        for line in frame.locator("body").inner_text(timeout=3000).splitlines():
            if any(x in line.casefold() for x in ("error", "debe tener", "errores")):
                print("LINE:", line)

    page.screenshot(path="reports/probe_real_contract.png", full_page=True)
    page.wait_for_timeout(2000)
    browser.close()
