"""Boot sequence.

Pure theatre, and worth it: the typed check-list is what makes the HUD feel
like instrumentation rather than a dashboard. It also does real work — each
line resolves against actual state, so a missing catalogue or an unreachable
host shows up here before you go looking for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Static

from hud.widgets.sphere import CoreSphere, SphereState

DOTS_WIDTH = 34


@dataclass
class BootLine:
    label: str
    resolve: str = "OK"
    detail: str = ""
    ok: bool = True


class BootScreen(Screen[None]):
    """Types a check-list, then hands over to the main grid."""

    DEFAULT_CSS = """
    BootScreen {
        background: $background;
        align: center middle;
    }
    BootScreen #boot-body {
        width: 62;
        height: auto;
    }
    BootScreen CoreSphere {
        height: 12;
        width: 100%;
    }
    BootScreen #boot-title {
        width: 100%;
        text-align: center;
        color: $accent;
        text-style: bold;
        margin: 1 0;
    }
    BootScreen #boot-log {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, lines: list[BootLine], *, accent: str, fps: int = 30) -> None:
        super().__init__()
        self._lines = lines
        self._accent = accent
        self._fps = fps
        self._shown: list[BootLine] = []
        self._log: Static | None = None
        self._finishing = False

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="boot-body"):
                    sphere = CoreSphere(fps=self._fps, accent=self._accent)
                    sphere.set_state(SphereState.POLLING)
                    yield sphere
                    yield Static("H U D  ·  CONTROL", id="boot-title")
                    self._log = Static("", id="boot-log")
                    yield self._log

    def on_mount(self) -> None:
        self.set_interval(0.11, self._advance)

    def _advance(self) -> None:
        if len(self._shown) >= len(self._lines):
            if not self._finishing:
                self._finishing = True
                self.set_timer(0.45, self._finish)
            return
        self._shown.append(self._lines[len(self._shown)])
        self._redraw()

    def _redraw(self) -> None:
        if self._log is None:
            return
        text = Text()
        for i, line in enumerate(self._shown):
            pad = "." * max(2, DOTS_WIDTH - len(line.label))
            text.append(line.label, style="bold" if i == len(self._shown) - 1 else "")
            text.append(f" {pad} ", style="dim")
            text.append(line.resolve, style="bold green" if line.ok else "bold red")
            if line.detail:
                text.append(f"  {line.detail}", style="dim")
            text.append("\n")
        self._log.update(text)

    def _finish(self) -> None:
        # Only dismiss once; the interval keeps firing until the screen pops.
        if self.is_running:
            self.dismiss(None)
