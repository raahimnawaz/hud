"""How a command is expressed. Orthogonal to *where* it runs (see host.py).

Pairing these two seams is what lets one set of backends serve both "run it on
this Mac" and "run it on the Windows box over SSH" without them being two
different systems.

Only the macOS backend is verified on this machine. Linux and Windows are
written against documented behaviour and are marked unverified until run on the
real hosts.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from hud.core.action import Action, Danger, PowerOp

PlatformId = Literal["macos", "linux", "windows"]


@dataclass(frozen=True)
class Proc:
    pid: int
    name: str
    cpu_percent: float = 0.0
    rss_mb: float = 0.0


@runtime_checkable
class Platform(Protocol):
    id: PlatformId
    verified: bool

    def power(self, op: PowerOp) -> Action: ...
    def quit_app(self, pid: int, name: str) -> Action: ...
    def kill_app(self, pid: int, name: str) -> Action: ...
    def open_path(self, path: str) -> Action: ...
    def reveal(self, path: str) -> Action: ...
    def open_url(self, url: str) -> Action: ...
    def open_in_editor(self, path: str, editor: str | None) -> Action: ...
    def terminal(self, cwd: str, command: str | None) -> Action: ...


def _editor_argv(path: str, editor: str | None) -> list[str] | None:
    """Prefer a CLI editor on PATH — it is the one form that works identically
    on all three platforms. Returns None when there is nothing to use, letting
    each platform fall back to its own document-opening mechanism.
    """
    for candidate in ([editor] if editor else []) + ["code", "cursor", "subl", "zed"]:
        if candidate and (found := shutil.which(candidate)):
            return [found, path]
    return None


@dataclass(frozen=True)
class MacOS:
    id: PlatformId = "macos"
    verified: bool = True

    def power(self, op: PowerOp) -> Action:
        """Power verbs on macOS go through System Events, not `sudo shutdown`.

        System Events asks each app to quit, which means unsaved-work dialogs
        still appear and the user can still cancel. It also needs no password —
        so the HUD never has to handle a credential to power the machine down.
        """
        match op:
            case PowerOp.SHUTDOWN:
                return Action(
                    "Shut down",
                    ["osascript", "-e", 'tell app "System Events" to shut down'],
                    Danger.DESTRUCTIVE,
                )
            case PowerOp.RESTART:
                return Action(
                    "Restart",
                    ["osascript", "-e", 'tell app "System Events" to restart'],
                    Danger.DESTRUCTIVE,
                )
            case PowerOp.SLEEP:
                return Action("Sleep", ["pmset", "sleepnow"], Danger.CAUTION)
            case PowerOp.LOCK:
                return Action(
                    "Lock screen", ["pmset", "displaysleepnow"], Danger.CAUTION
                )
            case PowerOp.LOGOUT:
                return Action(
                    "Log out",
                    ["osascript", "-e", 'tell app "System Events" to log out'],
                    Danger.CAUTION,
                )
        raise ValueError(op)

    def quit_app(self, pid: int, name: str) -> Action:
        """Polite quit: the app gets to prompt about unsaved work.

        Deliberately a separate action from kill_app — this never silently
        escalates to a force-kill if the app declines to close.
        """
        # `name` is the bundle name the OS knows ("Webots"), not a display
        # label. Bundle identifiers are addressed with `application id`.
        selector = "application id" if name.startswith("com.") else "application"
        return Action(
            f"Quit {name}",
            ["osascript", "-e", f'tell {selector} "{name}" to quit'],
            Danger.CAUTION,
        )

    def kill_app(self, pid: int, name: str) -> Action:
        return Action(f"Force-kill {name}", ["kill", "-9", str(pid)], Danger.DESTRUCTIVE)

    def open_path(self, path: str) -> Action:
        return Action(f"Open {path}", ["open", path], Danger.SAFE, detach=True)

    def reveal(self, path: str) -> Action:
        return Action("Reveal in Finder", ["open", "-R", path], Danger.SAFE, detach=True)


@dataclass(frozen=True)
class Linux:
    id: PlatformId = "linux"
    verified: bool = False

    def power(self, op: PowerOp) -> Action:
        """systemctl works locally via polkit.

        Over SSH it will fail: polkit treats an SSH session as non-local and
        refuses without an interactive agent. The documented fix is a narrowly
        scoped NOPASSWD sudoers entry for exactly this binary — opt-in per host
        via hosts.toml, never enabled by default.
        """
        match op:
            case PowerOp.SHUTDOWN:
                return Action("Shut down", ["systemctl", "poweroff"], Danger.DESTRUCTIVE)
            case PowerOp.RESTART:
                return Action("Restart", ["systemctl", "reboot"], Danger.DESTRUCTIVE)
            case PowerOp.SLEEP:
                return Action("Suspend", ["systemctl", "suspend"], Danger.CAUTION)
            case PowerOp.LOCK:
                return Action("Lock session", ["loginctl", "lock-session"], Danger.CAUTION)
            case PowerOp.LOGOUT:
                return Action(
                    "Log out",
                    ["loginctl", "terminate-user", "$USER"],
                    Danger.CAUTION,
                )
        raise ValueError(op)

    def quit_app(self, pid: int, name: str) -> Action:
        return Action(f"Quit {name}", ["kill", "-TERM", str(pid)], Danger.CAUTION)

    def kill_app(self, pid: int, name: str) -> Action:
        return Action(f"Force-kill {name}", ["kill", "-9", str(pid)], Danger.DESTRUCTIVE)

    def open_path(self, path: str) -> Action:
        return Action(f"Open {path}", ["xdg-open", path], Danger.SAFE, detach=True)

    def reveal(self, path: str) -> Action:
        return Action("Open folder", ["xdg-open", path], Danger.SAFE, detach=True)


@dataclass(frozen=True)
class Windows:
    id: PlatformId = "windows"
    verified: bool = False

    def power(self, op: PowerOp) -> Action:
        """Note: from inside a WSL session these same .exe names work via WSL
        interop, so one SSH target into WSL reaches the Windows host too.
        """
        match op:
            case PowerOp.SHUTDOWN:
                return Action("Shut down", ["shutdown.exe", "/s", "/t", "0"], Danger.DESTRUCTIVE)
            case PowerOp.RESTART:
                return Action("Restart", ["shutdown.exe", "/r", "/t", "0"], Danger.DESTRUCTIVE)
            case PowerOp.SLEEP:
                return Action(
                    "Sleep",
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    Danger.CAUTION,
                )
            case PowerOp.LOCK:
                return Action(
                    "Lock workstation",
                    ["rundll32.exe", "user32.dll,LockWorkStation"],
                    Danger.CAUTION,
                )
            case PowerOp.LOGOUT:
                return Action("Log out", ["shutdown.exe", "/l"], Danger.CAUTION)
        raise ValueError(op)

    def quit_app(self, pid: int, name: str) -> Action:
        # taskkill without /F sends WM_CLOSE, so the app can still prompt to save.
        return Action(f"Quit {name}", ["taskkill.exe", "/PID", str(pid)], Danger.CAUTION)

    def kill_app(self, pid: int, name: str) -> Action:
        return Action(
            f"Force-kill {name}",
            ["taskkill.exe", "/F", "/PID", str(pid)],
            Danger.DESTRUCTIVE,
        )

    def open_path(self, path: str) -> Action:
        return Action(f"Open {path}", ["cmd.exe", "/c", "start", "", path], Danger.SAFE, detach=True)

    def reveal(self, path: str) -> Action:
        return Action("Show in Explorer", ["explorer.exe", path], Danger.SAFE, detach=True)


PLATFORMS: dict[str, Platform] = {
    "macos": MacOS(),
    "linux": Linux(),
    "windows": Windows(),
}


def local_platform() -> Platform:
    if sys.platform == "darwin":
        return PLATFORMS["macos"]
    if sys.platform.startswith("linux"):
        return PLATFORMS["linux"]
    if sys.platform in ("win32", "cygwin"):
        return PLATFORMS["windows"]
    raise RuntimeError(f"unsupported platform: {sys.platform}")
