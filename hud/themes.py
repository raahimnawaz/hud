"""Themes.

The defaults (`lattice`, `gotham`) follow the restraint of defence/intel
console design — Palantir Gotham, Anduril Lattice — rather than the neon
cyberpunk register:

  * near-black *neutral* backgrounds, not pure black and not blue-glow
  * an almost monochrome palette: cool grey carries the information, and a
    single accent is spent sparingly on what is live
  * desaturated semantic colours — nothing at full chroma, because a table
    where four things are shouting reads as noise
  * chrome recedes. Borders are hairlines a shade above the surface, so the
    data is the brightest thing on screen

`arc-reactor` and `matrix` are kept as the loud alternates. Press `t` to cycle.

`accent` doubles as the sphere's idle colour, so switching theme retints the
core too.
"""

from __future__ import annotations

from textual.theme import Theme

# Anduril-ish: neutral graphite, warm amber signal.
LATTICE = Theme(
    name="lattice",
    primary="#5a6570",
    secondary="#3a424b",
    accent="#e0873c",
    foreground="#b6bec7",
    background="#0a0b0c",
    surface="#0e1012",
    panel="#15181c",
    success="#6f9c7d",
    warning="#c9a052",
    error="#c96f6f",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#e0873c",
        "footer-description-foreground": "#7c8790",
        "input-selection-background": "#e0873c25",
    },
)

# Palantir-ish: deep blue-black, desaturated steel cyan.
GOTHAM = Theme(
    name="gotham",
    primary="#47606f",
    secondary="#2e3d47",
    accent="#5fa8c7",
    foreground="#a3b4c2",
    background="#080c11",
    surface="#0d1319",
    panel="#131c25",
    success="#6a9d8c",
    warning="#c3a24a",
    error="#c26b6b",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#5fa8c7",
        "footer-description-foreground": "#6d7f8d",
        "input-selection-background": "#5fa8c725",
    },
)

ARC_REACTOR = Theme(
    name="arc-reactor",
    primary="#0090b0",
    secondary="#00647a",
    accent="#00d9ff",
    foreground="#a9d8e6",
    background="#04070a",
    surface="#080e14",
    panel="#0b1620",
    success="#3fbf90",
    warning="#d9a441",
    error="#e05c5c",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#00d9ff",
        "input-selection-background": "#00d9ff25",
    },
)

MATRIX = Theme(
    name="matrix",
    primary="#00913a",
    secondary="#00631f",
    accent="#00ff41",
    foreground="#8fce9f",
    background="#000600",
    surface="#020d02",
    panel="#03160a",
    success="#00cc41",
    warning="#a8cc00",
    error="#e04545",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#00ff41",
        "input-selection-background": "#00ff4125",
    },
)

THEMES = [LATTICE, GOTHAM, ARC_REACTOR, MATRIX]

ACCENTS = {t.name: t.accent for t in THEMES}
