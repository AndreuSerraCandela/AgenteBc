"""Listar acciones visibles en la ficha."""
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
    for i in range(frame.locator("button:visible").count()):
        btn = frame.locator("button:visible").nth(i)
        t = (btn.get_attribute("title") or "")
        a = (btn.get_attribute("aria-label") or "")
        txt = btn.inner_text(timeout=200).strip().replace("\n", " ")
        if any("firm" in x.casefold() for x in (t, a, txt)):
            print("MATCH", i, repr(t), repr(a), repr(txt))
    # open "Mostrar el resto" menu
    more = frame.locator('button[title*="Mostrar el resto" i]').first
    if more.count():
        more.click()
        page.wait_for_timeout(1000)
        for item in frame.locator('[role="menuitem"], [role="option"]').all():
            txt = item.inner_text(timeout=300)
            if "firm" in txt.casefold() or "estado" in txt.casefold():
                print("menu", repr(txt))
    page.wait_for_timeout(2000)
    browser.close()
