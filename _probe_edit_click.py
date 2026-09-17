"""Prueba clic en modo edición y estado del campo Estado."""
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
    page.wait_for_timeout(5000)

    frame = page.frames[1]
    edit = frame.locator('button[title*="Realizar cambios" i]')
    print("edit buttons:", edit.count())
    if edit.count():
        print("title:", edit.first.get_attribute("title"))
        edit.first.click()
        page.wait_for_timeout(1500)

    for label in ("Guardar", "Save", "Descartar"):
        btn = frame.get_by_role("button", name=label)
        print(f"{label} visible:", btn.count() and btn.first.is_visible())

    estado = frame.get_by_role("textbox", name="Estado").first
    print("Estado readonly attr:", estado.get_attribute("readonly"))
    print("Estado aria-disabled:", estado.get_attribute("aria-disabled"))
    print("Estado class:", (estado.get_attribute("class") or "")[:120])

    page.wait_for_timeout(5000)
    browser.close()
