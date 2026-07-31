"""BracketFrame — panel chrome.

Deliberately quiet. The chrome is a hairline one shade above the surface and
the label is dim tracked caps, so the brightest thing on screen is always the
data rather than the box around it. That restraint is most of what separates a
console that looks engineered from one that looks like a toy.

Terminals have no letter-spacing, so tracking is faked the only way available:
a space between every character. `PROJECTS` becomes `P R O J E C T S`, which
reads as the wide small-caps labelling these interfaces use for section heads.
"""

from __future__ import annotations

from textual.containers import Vertical


def track(text: str) -> str:
    """Fake letter-spacing by interleaving spaces."""
    return " ".join(text.upper())


class BracketFrame(Vertical):
    """A titled panel with a status line in the bottom border."""

    DEFAULT_CSS = """
    BracketFrame {
        border: solid $panel;
        border-title-align: left;
        border-title-color: $foreground 55%;
        border-subtitle-align: right;
        border-subtitle-color: $foreground 40%;
        background: $surface;
        padding: 1 2;
    }
    BracketFrame:focus-within {
        border: solid $primary;
        border-title-color: $accent;
    }
    BracketFrame.-degraded {
        border: solid $warning 45%;
        border-subtitle-color: $warning 75%;
    }
    BracketFrame.-error {
        border: solid $error 65%;
        border-subtitle-color: $error;
    }
    """

    def __init__(self, title: str, *children, status: str = "", **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self._title_text = title
        self.border_title = f" {track(title)} "
        self.border_subtitle = f" {status} " if status else ""

    def set_status(self, status: str, *, level: str = "ok") -> None:
        """Update the subtitle and tint the border by health.

        `level` is one of ok | degraded | error. Degraded is the normal state
        for a provider whose backend is simply absent (Docker not running, a
        host unreachable) — it must never read as a crash.
        """
        self.border_subtitle = f" {status} " if status else ""
        self.set_class(level == "degraded", "-degraded")
        self.set_class(level == "error", "-error")
