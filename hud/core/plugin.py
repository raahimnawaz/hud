"""The plugin contract.

Three rules the core enforces, and the reasons they exist:

1. Nothing blocks the UI. `refresh` is awaited inside a Textual Worker on the
   plugin's own interval, never on the render path.
2. Providers degrade, never crash. A dead daemon or a missing binary is a
   status string, not a traceback. `refresh` is expected to catch its own
   errors and record them in `error`.
3. Commands are the primary interface. Panels are the ambient view; the palette
   is how work actually gets done, which is what keeps the UI usable past a
   handful of plugins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from textual.widget import Widget

    from hud.core.action import Command
    from hud.core.target import Target


@runtime_checkable
class Plugin(Protocol):
    id: str
    title: str
    refresh_interval: float
    error: str | None

    def panel(self) -> Widget | None:
        """The dashboard tile, or None for palette-only plugins."""
        ...

    def commands(self) -> Iterable[Command]:
        """Palette entries. Called after every refresh, so it may reflect state."""
        ...

    async def refresh(self, target: Target) -> None:
        """Collect state. Runs in a Worker. Must not raise."""
        ...


class BasePlugin:
    """Convenience base handling the bookkeeping every plugin repeats."""

    id: str = "base"
    title: str = "BASE"
    refresh_interval: float = 10.0

    def __init__(self) -> None:
        self.error: str | None = None
        self._panel: Widget | None = None

    def panel(self) -> Widget | None:
        return self._panel

    def commands(self) -> Iterable[Command]:
        return ()

    async def refresh(self, target: Target) -> None:
        return None
