"""Comparar campos editables tras activar edición."""
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


def control_info(frame, caption):
    cap = frame.get_by_text(caption, exact=True).first
    container = cap.locator("xpath=ancestor::div[contains(@class,'ms-nav-edit-control-container')][1]")
    if not container.count():
        return caption, "no container"
    cls = container.get_attribute("class") or ""
    disabled = "edit-control-disabled" in cls
    val = container.locator('[role="textbox"]').first
    text = ""
    try:
        text = val.inner_text(timeout=300)
    except Exception:
        pass
    return caption, f"disabled={disabled} value={text!r}"


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
    for cap in ("Estado", "Tipo Venta", "Nº Cliente", "Comentario Cabecera"):
        print("BEFORE", control_info(frame, cap))
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2500)
    for cap in ("Estado", "Tipo Venta", "Nº Cliente", "Comentario Cabecera"):
        print("AFTER ", control_info(frame, cap))
    page.wait_for_timeout(2000)
    browser.close()
