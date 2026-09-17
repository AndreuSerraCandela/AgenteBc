"""Probar interacción con caption Estado."""
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

    # scroll general section
    frame.get_by_text("General", exact=True).first.click()
    page.wait_for_timeout(500)

    container = frame.locator('[controlname="Estado Contrato"]')
    print("container count", container.count())
    if container.count():
        print("class", container.first.get_attribute("class"))
        cap = container.locator('[role="button"]').first
        cap.click()
        page.wait_for_timeout(500)
        val = container.locator('[role="textbox"]').first
        val.click()
        page.wait_for_timeout(300)
        val.dblclick()
        page.wait_for_timeout(300)
        page.keyboard.press("F4")
        page.wait_for_timeout(800)
        print("options", frame.get_by_role("option").count())

    # try with edit mode
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(1500)
    container = frame.locator('[controlname="Estado Contrato"]')
    print("after edit class", container.first.get_attribute("class"))
    val = container.locator('[role="textbox"]').first
    val.click()
    page.keyboard.press("F4")
    page.wait_for_timeout(800)
    print("options after edit", frame.get_by_role("option").count())
    for i in range(min(frame.get_by_role("option").count(), 10)):
        print(i, frame.get_by_role("option").nth(i).inner_text(timeout=300))

    page.wait_for_timeout(2000)
    browser.close()
