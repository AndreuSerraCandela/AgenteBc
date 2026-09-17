"""Estado tras activar edición."""
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


def dump(frame, label):
    print(f"\n--- {label} ---")
    for i in range(min(frame.locator("button:visible").count(), 12)):
        btn = frame.locator("button:visible").nth(i)
        print(i, repr(btn.get_attribute("title")), repr(btn.inner_text(timeout=300)[:20]))
    estado = frame.get_by_role("textbox", name="Estado").first
    print("Estado class:", (estado.get_attribute("class") or "")[:100])
    tipo = frame.get_by_role("textbox", name="Tipo Venta")
    if tipo.count():
        print("Tipo class:", (tipo.first.get_attribute("class") or "")[:100])


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
    dump(frame, "before")
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2500)
    dump(frame, "after edit click")
    page.wait_for_timeout(3000)
    browser.close()
