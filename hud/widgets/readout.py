"""CoreReadout — the identity block under the sphere.

Deliberately not a system monitor: this reports what the HUD is bound to
(target, platform, how much is loaded) rather than CPU and memory. Vitals are
their own plugin when they're wanted.

`Digits` is used for the clock because it renders tall seven-segment numerals,
which is the single most control-panel-looking widget Textual ships.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Digits, Static


class CoreReadout(Vertical):
    DEFAULT_CSS = """
    CoreReadout {
        height: auto;
        margin: 1 0 0 0;
    }
    CoreReadout Digits {
        width: 100%;
        color: $accent;
        height: 3;
    }
    CoreReadout #core-facts {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._facts: list[tuple[str, str]] = []
        self._clock: Digits | None = None
        self._body: Static | None = None
        self._started = time.monotonic()

    def compose(self) -> ComposeResult:
        self._clock = Digits("00:00:00")
        yield self._clock
        self._body = Static("", id="core-facts")
        yield self._body

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._tick()

    def set_facts(self, facts: list[tuple[str, str]]) -> None:
        self._facts = facts
        self._redraw()

    def _tick(self) -> None:
        if self._clock is not None:
            self._clock.update(time.strftime("%H:%M:%S"))
        self._redraw()

    def _redraw(self) -> None:
        if self._body is None:
            return
        elapsed = int(time.monotonic() - self._started)
        rows = [
            *self._facts,
            ("UPTIME", f"{elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"),
        ]
        text = Text()
        for key, value in rows:
            text.append(f"{key:<8}", style="dim")
            text.append(f"{value}\n")
        self._body.update(text)
