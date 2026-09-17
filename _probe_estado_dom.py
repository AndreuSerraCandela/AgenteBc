"""Explorar DOM del campo Estado."""
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
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2000)

    caption = frame.get_by_text("Estado", exact=True).first
    row = caption.locator("xpath=ancestor::*[self::tr or self::div][1]")
    html = row.evaluate("el => el.outerHTML")
    print(html[:2500])

    estado = frame.get_by_role("textbox", name="Estado").first
    for action in ("click", "dblclick"):
        print(f"\n=== {action} textbox ===")
        getattr(estado, action)()
        page.wait_for_timeout(800)
        print("options", frame.get_by_role("option").count())
        print("listbox", frame.get_by_role("listbox").count())
        print("menu", frame.get_by_role("menu").count())
        combos = frame.locator('[role="combobox"]')
        print("comboboxes visible", combos.count())

    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(800)
    print("after alt+down options", frame.get_by_role("option").count())

    page.wait_for_timeout(2000)
    browser.close()
