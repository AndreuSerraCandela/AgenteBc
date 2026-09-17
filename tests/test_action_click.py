def test_action_button_selector_prefers_menuitem_when_opened_from_menu() -> None:
    from agentebc.web_preview import _css_string

    label = "Registrar"
    escaped = _css_string(label)
    menu_selector = f'button[role="menuitem"][aria-label="{escaped}"]'
    split_selector = (
        f'button[aria-label="{escaped}"][data-top-level-action="true"]'
    )

    assert 'role="menuitem"' in menu_selector
    assert "data-top-level-action" in split_selector
    assert menu_selector != split_selector
