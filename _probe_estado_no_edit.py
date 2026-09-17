"""Cambiar Estado SIN pulsar Editar."""
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

    estado = frame.get_by_role("textbox", name="Estado").first
    print("class before:", (estado.get_attribute("class") or "")[:80])
    estado.click()
    page.wait_for_timeout(500)
    estado.dblclick()
    page.wait_for_timeout(500)
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(800)
    opts = frame.get_by_role("option")
    print("options:", opts.count())
    for i in range(min(opts.count(), 12)):
        print(i, opts.nth(i).inner_text(timeout=300))
    firmado = frame.get_by_role("option", name="Firmado")
    if firmado.count():
        firmado.first.click()
        page.wait_for_timeout(2000)
    body = frame.locator("body").inner_text(timeout=3000)
    for line in body.splitlines():
        if any(x in line.casefold() for x in ("error", "debe tener", "errores")):
            print("LINE:", line)
    page.wait_for_timeout(3000)
    browser.close()
