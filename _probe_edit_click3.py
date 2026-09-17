"""Diagnóstico detallado del botón editar y campo Estado."""
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

    edit = frame.locator('button[title*="Realizar cambios" i]').first
    print("edit disabled:", edit.is_disabled())
    print("edit aria-disabled:", edit.get_attribute("aria-disabled"))
    print("edit title before:", edit.get_attribute("title"))

    edit.click(force=True)
    page.wait_for_timeout(2500)
    print("edit title after:", edit.get_attribute("title"))

    # all toolbar buttons first 8
    for i in range(8):
        btn = frame.locator("button:visible").nth(i)
        print(
            i,
            "title=",
            repr(btn.get_attribute("title")),
            "disabled=",
            btn.is_disabled(),
        )

    estado_btn = frame.get_by_role("button", name="Estado")
    print("Estado buttons:", estado_btn.count())
    for i in range(estado_btn.count()):
        b = estado_btn.nth(i)
        print(
            "  btn",
            i,
            "visible",
            b.is_visible(),
            "class",
            (b.get_attribute("class") or "")[:60],
            "disabled",
            b.is_disabled(),
        )

    # try click estado dropdown button
    for i in range(estado_btn.count()):
        b = estado_btn.nth(i)
        if b.is_visible():
            b.click()
            page.wait_for_timeout(1000)
            opts = frame.locator('[role="option"], [role="listbox"] *')
            print("options after click:", opts.count())
            for j in range(min(opts.count(), 10)):
                print(" ", opts.nth(j).inner_text(timeout=300))
            break

    tipo = frame.get_by_role("textbox", name="Tipo Venta")
    if tipo.count():
        print("Tipo Venta class:", (tipo.first.get_attribute("class") or "")[:80])

    page.wait_for_timeout(3000)
    browser.close()
