"""Inspeccionar flyout de validación y botón compartir."""
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


def set_firmado(frame, page):
    btn = frame.locator('button[aria-label*="General" i][aria-label*="Mostrar" i]').first
    if btn.count() and btn.is_visible():
        btn.click(force=True)
        page.wait_for_timeout(600)
    frame.locator('button[title*="Realizar cambios" i]').first.click()
    page.wait_for_timeout(1500)
    c = frame.locator('[controlname="Estado Contrato"]')
    c.scroll_into_view_if_needed()
    c.locator('[role="textbox"]').first.click()
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(800)
    frame.get_by_role("option", name="Firmado").first.click()
    page.wait_for_timeout(2000)
    page.keyboard.press("Tab")
    page.wait_for_timeout(300)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=False)
    context = browser.new_context(viewport={"width": 1440, "height": 1200})
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if page.locator('input[type="password"]').count():
        page.locator('input[type="text"]').first.fill(settings.username or "")
        page.locator('input[type="password"]').first.fill(settings.password or "")
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_timeout(3000)
    page.wait_for_timeout(6000)
    frame = page.frames[1]
    set_firmado(frame, page)

    container = frame.locator('[controlname="Estado Contrato"]')
    box = container.bounding_box()
    if box:
        page.mouse.click(box["x"] + 20, box["y"] + box["height"] / 2)
        page.wait_for_timeout(800)

    tip = frame.get_by_text("ha revelado un problema", exact=False)
    print("tip count", tip.count())
    if tip.count():
        pop = tip.first.locator(
            "xpath=ancestor::*[self::div or self::section][position()<=6][1]"
        )
        for _ in range(6):
            pop = tip.first.locator("xpath=ancestor::div[1]")
            try:
                html = pop.evaluate("el => el.outerHTML")
                if "button" in html.lower():
                    print("POP HTML:", html[:1500])
                    break
                tip = pop
            except Exception:
                break

    for sel in (
        ':text("ha revelado un problema")',
        '[class*="validation"]',
        '[class*="flyout"]',
        '[class*="callout"]',
    ):
        loc = frame.locator(sel)
        print(sel, loc.count())

    buttons = frame.locator("button:visible")
    print("visible buttons", buttons.count())
    for i in range(min(buttons.count(), 25)):
        b = buttons.nth(i)
        t = b.get_attribute("title") or ""
        a = b.get_attribute("aria-label") or ""
        c = (b.get_attribute("class") or "")[:60]
        if any(x in (t + a).casefold() for x in ("compartir", "share", "copiar", "copy")):
            print("BTN", i, "title", repr(t), "aria", repr(a), "class", c)

    # try popover share: buttons near validation text
    if tip.count():
        ancestor = tip.first.locator("xpath=ancestor::div[.//button][1]")
        if ancestor.count():
            abtns = ancestor.locator("button")
            print("ancestor buttons", abtns.count())
            for i in range(abtns.count()):
                b = abtns.nth(i)
                print(" ab", i, b.get_attribute("title"), b.get_attribute("aria-label"), b.get_attribute("class"))

    page.wait_for_timeout(5000)
    browser.close()
