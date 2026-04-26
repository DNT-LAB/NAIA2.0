from ui.theme import get_custom_styles, get_dynamic_styles, get_legacy_dark_styles


def test_theme_style_dictionaries_are_cached():
    assert get_dynamic_styles() is get_dynamic_styles()
    assert get_dynamic_styles() is get_legacy_dark_styles()
    assert get_custom_styles() is get_custom_styles()
