"""Keep Forge extra-network directives opaque while normalizing ordinary prompt text."""

import re


WEBUI_NETWORK_TOKEN = re.compile(r"<(?:lora|lyco|hypernet):[^>]*>", re.IGNORECASE)


def protect_webui_tokens(text):
    """Return editable text and a function restoring the exact matched substrings."""
    marker = "\ue000WEBUI"
    while marker in text:
        marker += "_"
    originals = {}

    def hide(match):
        key = f"{marker}{len(originals)}\ue001"
        originals[key] = match[0]
        return key

    masked = WEBUI_NETWORK_TOKEN.sub(hide, text)

    def restore(value):
        for key, original in originals.items():
            value = value.replace(key, original)
        return value

    return masked, restore
