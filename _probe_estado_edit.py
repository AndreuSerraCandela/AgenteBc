"""Intentar cambiar Estado en modo edición."""
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


def field_text(loc):
    try:
        return loc.input_value()
    except Exception:
        return loc.inner_text(timeout=500).strip()


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
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2000)

    estado_tb = frame.get_by_role("textbox", name="Estado").first
    print("Estado value before:", field_text(estado_tb))

    estado_btn = frame.get_by_role("button", name="Estado")
    print("Estado buttons:", estado_btn.count())
    for i in range(estado_btn.count()):
        b = estado_btn.nth(i)
        if not b.is_visible():
            continue
        print("click estado button", i, "title", repr(b.get_attribute("title")))
        b.click()
        page.wait_for_timeout(1000)
        opts = frame.get_by_role("option")
        print("options:", opts.count())
        for j in range(min(opts.count(), 15)):
            print(" ", j, opts.nth(j).inner_text(timeout=300))
        firmado = frame.get_by_role("option", name="Firmado")
        if firmado.count() and firmado.first.is_visible():
            firmado.first.click()
            page.wait_for_timeout(2000)
        break

    print("Estado value after:", field_text(estado_tb))
    body = frame.locator("body").inner_text(timeout=3000)
    for line in body.splitlines():
        low = line.casefold()
        if "error" in low or "debe tener" in low or "errores" in low:
            print("LINE:", line)

    page.wait_for_timeout(3000)
    browser.close()
