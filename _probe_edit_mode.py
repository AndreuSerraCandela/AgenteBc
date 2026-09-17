"""Inspecciona controles de edición en la ficha de contrato BC."""
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
print("URL:", url)

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
    for frame in page.frames:
        print("\n=== FRAME", frame.url[:80], "===")
        try:
            buttons = frame.locator("button:visible")
            count = buttons.count()
            print("visible buttons:", count)
            for i in range(min(count, 40)):
                btn = buttons.nth(i)
                label = (btn.get_attribute("aria-label") or "").strip()
                title = (btn.get_attribute("title") or "").strip()
                text = btn.inner_text(timeout=500).strip().replace("\n", " ")
                if label or title or text:
                    print(f"  [{i}] aria={label!r} title={title!r} text={text!r}")
        except Exception as exc:
            print("buttons error:", exc)

        try:
            estado = frame.get_by_text("Estado", exact=True)
            print("Estado matches:", estado.count())
            for role in ("combobox", "textbox", "button"):
                c = frame.get_by_role(role, name="Estado")
                print(f"  role={role} name=Estado:", c.count())
        except Exception as exc:
            print("estado error:", exc)

    page.wait_for_timeout(3000)
    browser.close()
