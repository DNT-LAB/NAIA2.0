"""Stylesheet loader for native img2img/inpaint PyQt surfaces."""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_img2img_window_stylesheet() -> str:
    """Load the CSS-like Qt stylesheet shared by img2img and inpaint windows."""
    return Path(__file__).with_name("img2img_window_style.css").read_text(encoding="utf-8")
