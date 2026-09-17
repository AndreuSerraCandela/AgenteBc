"""Prueba varias formas de activar edición."""
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


def estado_class(frame):
    loc = frame.get_by_role("textbox", name="Estado").first
    return (loc.get_attribute("class") or "")[:80]


def save_buttons(frame):
    found = []
    for title in ("Guardar", "Save", "Descartar", "Discard"):
        btn = frame.locator(f'button[title*="{title}" i], button[aria-label*="{title}" i]')
        if btn.count() and btn.first.is_visible():
            found.append(title)
    return found


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
    print("BEFORE class:", estado_class(frame), "buttons:", save_buttons(frame))

    edit = frame.locator('button[title*="Realizar cambios" i]').first
    edit.click()
    page.wait_for_timeout(2000)
    print("AFTER click class:", estado_class(frame), "buttons:", save_buttons(frame))

    page.keyboard.press("F9")
    page.wait_for_timeout(2000)
    print("AFTER F9 class:", estado_class(frame), "buttons:", save_buttons(frame))

    # list all buttons with guardar/descartar in title
    for i in range(frame.locator("button:visible").count()):
        btn = frame.locator("button:visible").nth(i)
        t = (btn.get_attribute("title") or "")
        if any(x in t.casefold() for x in ("guardar", "save", "descartar", "discard", "cambios")):
            print("btn", i, "title=", t)

    page.wait_for_timeout(3000)
    browser.close()
