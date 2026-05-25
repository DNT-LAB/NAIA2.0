"""Console output helpers that tolerate non-UTF-8 Windows consoles."""

from __future__ import annotations

import sys


def safe_print(message: object, *, flush: bool = False) -> None:
    text = str(message)
    try:
        print(text, flush=flush)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=flush)
