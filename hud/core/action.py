"""Every side effect in the HUD is an Action carrying a danger level and a target.

Nothing calls a subprocess directly. Plugins build Actions; the app decides what
confirmation an Action needs based on its danger, and only then runs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hud.core.target import Target


class Danger(IntEnum):
    """How much a mistake costs. Drives which confirmation gate applies."""

    SAFE = 0
    """Reversible and cheap: launch an app, focus a window, open an editor."""

    CAUTION = 1
    """Recoverable but disruptive: graceful quit, sleep, lock, log out."""

    DESTRUCTIVE = 2
    """Loses unsaved work or ends the session: force-kill, restart, shut down."""


class PowerOp(IntEnum):
    SHUTDOWN = 0
    RESTART = 1
    SLEEP = 2
    LOCK = 3
    LOGOUT = 4


@dataclass(frozen=True)
class Action:
    """A command to run somewhere, with enough context to confirm it safely.

    `argv` is always a list. Nothing in this codebase builds a shell string —
    see runner.py for why that matters once SSH is in play.
    """

    title: str
    argv: list[str]
    danger: Danger = Danger.SAFE
    target: Target | None = None
    detach: bool = False
    """Spawn and forget rather than waiting for output (GUI app launches)."""
    is_power: bool = False
    """Host power operation. Enforced against the target's allow_power opt-in
    inside the runner, so a plugin cannot route around the check by building
    the Action itself."""

    def describe_target(self) -> str:
        """Human-readable target name, always shown in confirmation dialogs.

        The whole point of naming the target is that 'shut down the wrong host'
        is the mistake a hold-to-confirm gesture cannot catch.
        """
        if self.target is None:
            return "this machine"
        return self.target.label


@dataclass
class Completed:
    """Result of a finished Action."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class Command:
    """A palette entry contributed by a plugin."""

    id: str
    title: str
    subtitle: str = ""
    action: Action | None = None
    keybind: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    """Extra words the fuzzy matcher should consider (repo paths, app ids)."""
