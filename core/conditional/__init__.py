"""Headless conditional-prompt block model + DSL round-trip + preset IO.

Ported PyQt-free from future01 ``modules/conditional`` so the headless Remote Web
editor can round-trip rules through the block model, serialize/parse the runtime
DSL, and persist user presets. No Qt/pandas dependencies (SDLC R-01 / R-05).
"""
