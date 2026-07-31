"""Power — host power operations, gated by danger level.

Palette-only: there is deliberately no panel and no keybinding for any of
these. Shutting the machine down should require going and looking for it, not
a stray keypress on a focused tile.

On macOS the shutdown and restart verbs route through System Events rather than
`sudo shutdown`, so applications are asked to quit, unsaved-work dialogs still
appear, and the HUD never needs to handle a password. See core/platform.py.
"""

from __future__ import annotations

from typing import Iterable

from hud.core.action import Command, PowerOp
from hud.core.plugin import BasePlugin
from hud.core.runner import power_action
from hud.core.target import Target

OPS: list[tuple[PowerOp, str, str]] = [
    (PowerOp.LOCK, "Lock screen", "reversible"),
    (PowerOp.SLEEP, "Sleep", "reversible"),
    (PowerOp.LOGOUT, "Log out", "closes your session"),
    (PowerOp.RESTART, "Restart", "unsaved work may be lost"),
    (PowerOp.SHUTDOWN, "Shut down", "unsaved work may be lost"),
]


class PowerPlugin(BasePlugin):
    id = "power"
    title = "power"
    refresh_interval = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._targets: list[Target] = []
        self.status = ""
        self.degraded = False

    def panel(self):
        return None

    async def refresh(self, target: Target) -> None:
        self.error = None
        # Only the local target is registered today; when SSH hosts are added
        # this becomes the full registry and every op gains a per-host variant.
        self._targets = [target]

    def commands(self) -> Iterable[Command]:
        for target in self._targets:
            for op, label, note in OPS:
                action = power_action(op, target)
                yield Command(
                    id=f"power.{op.name.lower()}.{target.host.alias}",
                    title=f"{label} — {target.label}",
                    subtitle=note,
                    action=action,
                    tags=("power", op.name.lower(), target.host.alias),
                )
