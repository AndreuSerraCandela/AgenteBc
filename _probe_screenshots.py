"""Capturas antes y después de Editar."""
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
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    frame = page.frames[1]
    frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first.click()
    page.wait_for_timeout(800)
    page.screenshot(path="reports/probe_before_edit.png")
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2000)
    page.screenshot(path="reports/probe_after_edit.png")
    container = frame.locator('[controlname="Estado Contrato"]')
    print("after class", container.get_attribute("class"))
    browser.close()
