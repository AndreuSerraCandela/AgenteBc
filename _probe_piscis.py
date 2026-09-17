"""Probar CTO02-P0001 en Piscis Dos Tres Hache, S.L."""
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from agentebc.config import Settings

COMPANY = "Piscis Dos Tres Hache, S.L."
CONTRACT = "CTO02-P0001"
settings = Settings.from_environment()
base = settings.odata_base_url.rsplit("/ODataV4", 1)[0]
query = urlencode(
    {
        "company": COMPANY,
        "page": "50209",
        "filter": f"'Sales Header'.'No.' IS '{CONTRACT}' AND 'Sales Header'.'Document Type' IS 'Order'",
    }
)
url = f"{base}/?{query}"


def dismiss_dialogs(page):
    for frame in page.frames:
        try:
            if not frame.locator('[role="dialog"]:visible').count():
                continue
            for label in ("Aceptar", "OK", "Cerrar"):
                btn = frame.get_by_role("button", name=label)
                if btn.count() and btn.first.is_visible():
                    btn.first.click(force=True)
                    page.wait_for_timeout(400)
                    return True
        except Exception:
            continue
    return False


def estado_value(frame):
    container = frame.locator('[controlname="Estado Contrato"]')
    if not container.count():
        return None
    val = container.locator('[role="textbox"]').first
    try:
        return val.get_attribute("title") or val.inner_text(timeout=500)
    except Exception:
        return val.inner_text(timeout=500)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=False)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    for _ in range(5):
        if not dismiss_dialogs(page):
            break
    frame = page.frames[1]

    show_more = frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first
    if show_more.count() and show_more.is_visible():
        show_more.click(force=True)
        page.wait_for_timeout(800)

    print("BEFORE:", estado_value(frame))
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(2000)
    print("IN EDIT:", estado_value(frame))

    container = frame.locator('[controlname="Estado Contrato"]')
    container.scroll_into_view_if_needed()
    val = container.locator('[role="textbox"]').first
    val.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(1000)
    opts = frame.get_by_role("option")
    print("options:", opts.count())
    firmado = frame.get_by_role("option", name="Firmado")
    if firmado.count() and firmado.first.is_visible():
        firmado.first.click()
        page.wait_for_timeout(2500)
    print("AFTER:", estado_value(frame))
    for line in frame.locator("body").inner_text(timeout=3000).splitlines():
        if any(x in line.casefold() for x in ("error", "debe tener", "errores", "comentario")):
            print("LINE:", line)

    page.screenshot(path="reports/probe_piscis_cto02.png", full_page=True)
    browser.close()
