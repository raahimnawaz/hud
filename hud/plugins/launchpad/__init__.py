"""Launchpad — a declarative catalogue of applications, with a detail view.

This is the piece that makes the HUD generic. No application is named anywhere
in this module: Webots, KiCad, a CAD package, an EDA tool, or anything else is
a few lines of YAML in ~/.config/hud/apps.yaml. Adding one requires no Python,
and that includes its detail view — see inspect.py.

Detection strategies, in priority order:
    bundle:  a macOS .app directory that exists
    path:    an absolute executable path that exists
    which:   a command name resolvable on PATH
    process: a process name to match when nothing on disk identifies it

Launch strategies:
    open:    hand a path to the OS opener (macOS `open`)
    exec:    an explicit argv, spawned detached
    url:     a deep link
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from hud.core.action import Action, Command, Danger
from hud.core.config import Config
from hud.core.plugin import BasePlugin
from hud.core.target import Target
from hud.plugins.launchpad.inspect import (
    InspectResult,
    InspectSpec,
    process_facts,
    run_inspector,
)

try:
    import psutil
except ImportError:  # degrade rather than crash
    psutil = None  # type: ignore[assignment]


INSTALL_CACHE_TTL = 60.0
"""Seconds between disk-detection sweeps. Installs change on a human
timescale, not a poll interval."""


def _platform_key() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "windows"


class AppStatus(Enum):
    ABSENT = "absent"
    INSTALLED = "installed"
    RUNNING = "running"


@dataclass
class AppSpec:
    id: str
    name: str
    glyph: str = "·"
    detect: dict[str, Any] = field(default_factory=dict)
    launch: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    inspectors: list[InspectSpec] = field(default_factory=list)

    status: AppStatus = AppStatus.ABSENT
    proc: dict[str, Any] | None = None
    results: list[InspectResult] = field(default_factory=list)

    @property
    def pid(self) -> int | None:
        return self.proc["pid"] if self.proc else None

    @property
    def os_name(self) -> str:
        """The name the OS knows this app by, which is not the display name.

        macOS `tell application "X" to quit` needs the bundle name ("Webots"),
        not our uppercase label ("WEBOTS"). Derived from the bundle path unless
        the YAML overrides it with `app_name`.
        """
        if override := self.detect.get("app_name"):
            return override
        if bundle := self.detect.get("bundle"):
            return Path(bundle).stem
        if path := self.detect.get("path"):
            return Path(path).stem
        if cmd := self.detect.get("which"):
            return cmd
        return self.name

    @classmethod
    def from_yaml(cls, raw: dict[str, Any]) -> AppSpec | None:
        """Accepts either the flat form (current platform only) or the
        per-platform form. Unknown platforms simply yield no entry.
        """
        if "platforms" in raw:
            block = raw["platforms"].get(_platform_key())
            if not block:
                return None
            detect = block.get("detect", {})
            launch = block.get("launch", {})
            actions = block.get("actions", raw.get("actions", []))
            inspect_raw = block.get("inspect", raw.get("inspect", []))
        else:
            detect = raw.get("detect", {})
            launch = raw.get("launch", {})
            actions = raw.get("actions", [])
            inspect_raw = raw.get("inspect", [])

        app_id = raw.get("id")
        if not app_id:
            return None

        inspectors = [
            spec
            for spec in (InspectSpec.from_yaml(i) for i in inspect_raw or [])
            if spec is not None
        ]

        return cls(
            id=app_id,
            name=raw.get("name", app_id.upper()),
            glyph=raw.get("glyph", "·"),
            detect=detect,
            launch=launch,
            actions=actions,
            inspectors=inspectors,
        )

    # ----- detection -------------------------------------------------------

    def installed_path(self) -> str | None:
        # expanduser matters: several tools install per-user rather than into
        # /Applications (Autodesk Fusion, for one).
        if bundle := self.detect.get("bundle"):
            resolved = Path(bundle).expanduser()
            return str(resolved) if resolved.exists() else None
        if path := self.detect.get("path"):
            resolved = Path(path).expanduser()
            return str(resolved) if resolved.exists() else None
        if cmd := self.detect.get("which"):
            return shutil.which(cmd)
        if self.detect.get("always"):
            # Web targets (Onshape, a self-hosted service) are bookmarks, not
            # installs. They are always reachable, and probing some unrelated
            # binary to fake presence — which an earlier version did — reports
            # tools as installed that simply are not.
            return self.launch.get("url", "web")
        # Process-only entries have nothing on disk to point at; presence is
        # decided entirely by the running-process scan.
        return None

    def matches_process(self, name: str | None, exe: str | None) -> bool:
        if wanted := self.detect.get("process"):
            return bool(name) and wanted.lower() in name.lower()
        if bundle := self.detect.get("bundle"):
            return bool(exe) and exe.startswith(bundle)
        if path := self.detect.get("path"):
            return exe == path
        if cmd := self.detect.get("which"):
            return bool(name) and name.lower() == cmd.lower()
        return False

    # ----- launching -------------------------------------------------------

    def launch_action(self) -> Action | None:
        if target := self.launch.get("open"):
            return Action(f"Launch {self.name}", ["open", target], Danger.SAFE, detach=True)
        if argv := self.launch.get("exec"):
            return Action(f"Launch {self.name}", list(argv), Danger.SAFE, detach=True)
        if url := self.launch.get("url"):
            return Action(f"Open {self.name}", ["open", url], Danger.SAFE, detach=True)
        return None


class LaunchpadPanel(Vertical):
    """Master-detail: the app list above, the selected app's detail below."""

    DEFAULT_CSS = """
    LaunchpadPanel > DataTable {
        height: 40%;
        min-height: 6;
        /* The columns are sized to fit; a horizontal scrollbar here reads as
           a stray filled bar across the panel rather than as a control. */
        scrollbar-size-horizontal: 0;
    }
    LaunchpadPanel > #app-detail {
        height: 1fr;
        padding: 1 0 0 0;
        overflow-y: auto;
    }
    """

    def __init__(self, plugin: LaunchpadPlugin) -> None:
        super().__init__()
        self._plugin = plugin

    def compose(self) -> ComposeResult:
        yield self._plugin.table
        yield self._plugin.detail

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Rebuilding the table re-emits this event as the cursor lands on a
        # row. Without both guards below that becomes a feedback loop —
        # refresh redraws the table, the redraw fires a highlight, the
        # highlight requests a refresh — and the plugin polls continuously
        # instead of on its interval.
        if self._plugin.rebuilding:
            return
        if event.row_key is None or event.row_key.value is None:
            return
        if not self._plugin.select(str(event.row_key.value)):
            return
        # Inspectors run for the selected app only, so a *changed* selection
        # has to trigger its own refresh rather than waiting for the next poll.
        self.app.refresh_plugin(self._plugin)


class LaunchpadPlugin(BasePlugin):
    id = "launchpad"
    title = "systems"
    refresh_interval = 5.0

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.apps: list[AppSpec] = []
        self.status = ""
        self.degraded = False
        self.selected_id: str | None = None
        self.rebuilding = False
        """True while the table is being redrawn, so the highlight events that
        redraw emits are ignored rather than treated as user selections."""
        self._platform = None
        """Captured on first refresh so commands() can build quit/kill actions
        through the current platform's vocabulary."""

        # psutil.Process objects are cached across refreshes because
        # cpu_percent() reports the delta since its own previous call on the
        # same object. Re-creating them every poll would report 0.0 forever,
        # which is exactly what the first version of this did.
        self._proc_cache: dict[int, Any] = {}

        # Disk detection changes on the timescale of installing software, not
        # of a poll interval.
        self._install_cache: dict[str, str | None] = {}
        self._install_checked_at = 0.0

        for raw in config.apps:
            if not isinstance(raw, dict):
                continue
            spec = AppSpec.from_yaml(raw)
            if spec is not None:
                self.apps.append(spec)

        self.table = DataTable(cursor_type="row", zebra_stripes=False)
        self.table.add_columns("APP", "STATE", "CPU", "MEM")
        self.detail = Static("", id="app-detail")
        self._panel = LaunchpadPanel(self)

    def select(self, app_id: str) -> bool:
        """Returns True only when the selection actually changed."""
        if app_id == self.selected_id:
            return False
        self.selected_id = app_id
        return True

    def _selected(self) -> AppSpec | None:
        if self.selected_id is not None:
            found = next((a for a in self.apps if a.id == self.selected_id), None)
            if found is not None:
                return found
        # Before the table has emitted a cursor event, fall back to something
        # useful: whatever is running, else the first installed tool.
        return next(
            (a for a in self.apps if a.status is AppStatus.RUNNING),
            next((a for a in self.apps if a.status is AppStatus.INSTALLED), None),
        )

    # ----- polling ---------------------------------------------------------

    async def refresh(self, target: Target) -> None:
        self.error = None
        self._platform = target.platform

        if not self.apps:
            self.status = "no apps configured"
            self.degraded = True
            self._render()
            return

        self._scan_processes()

        running = sum(1 for a in self.apps if a.status is AppStatus.RUNNING)
        present = sum(1 for a in self.apps if a.status is not AppStatus.ABSENT)

        if psutil is None:
            self.status = f"{present} of {len(self.apps)} known · psutil missing"
            self.degraded = True
        else:
            self.status = f"{running} active · {present} of {len(self.apps)} known"
            self.degraded = False

        await self._refresh_detail(target)
        self._render()

    def _scan_processes(self) -> None:
        """One process snapshot, matched against the apps that could be running.

        Two things keep this cheap with a ~90-entry catalogue:

        1. Disk detection is cached. Installs do not change every five seconds,
           and 90 stat calls per poll for a fact that changes monthly is waste.
        2. Only *installed* apps are matched against the process list. An app
           with nothing on disk cannot be running, so the expensive
           apps x processes comparison runs over the ~10 tools you actually
           have rather than the whole catalogue. Entries detected purely by
           process name have no disk presence and are always checked.
        """
        now = time.monotonic()
        if now - self._install_checked_at > INSTALL_CACHE_TTL:
            self._install_cache = {a.id: a.installed_path() for a in self.apps}
            self._install_checked_at = now

        candidates: list[AppSpec] = []
        for app in self.apps:
            app.proc = None
            path = self._install_cache.get(app.id)
            app.status = AppStatus.INSTALLED if path else AppStatus.ABSENT
            if path or app.detect.get("process"):
                candidates.append(app)

        if not candidates or psutil is None:
            return

        procs: list[tuple[int, str | None, str | None, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            # Short-lived processes routinely die mid-scan — including the
            # ones our own inspectors spawn. Every access is guarded.
            try:
                info = proc.info
                procs.append((info["pid"], info.get("name"), info.get("exe"), proc))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        live_pids: set[int] = set()

        for app in candidates:
            for pid, name, exe, handle in procs:
                if not app.matches_process(name, exe):
                    continue

                app.status = AppStatus.RUNNING
                live_pids.add(pid)

                try:
                    cached = self._proc_cache.get(pid)
                    if cached is None:
                        cached = handle
                        self._proc_cache[pid] = cached
                        cached.cpu_percent()  # prime; first call returns 0.0

                    with cached.oneshot():
                        app.proc = {
                            "pid": pid,
                            "cpu": cached.cpu_percent(),
                            "rss_mb": cached.memory_info().rss / 1_048_576,
                            "threads": cached.num_threads(),
                            "created": cached.create_time(),
                        }
                except Exception:
                    # Process vanished or is not readable — degrade to the
                    # bare fact that it is running.
                    app.proc = {"pid": pid}
                break

        for pid in set(self._proc_cache) - live_pids:
            self._proc_cache.pop(pid, None)

    async def _refresh_detail(self, target: Target) -> None:
        """Inspectors run for the selected app only — shelling out to every
        app's CLI on every poll would be wasteful for output nobody reads."""
        app = self._selected()
        if app is None:
            return
        if app.status is not AppStatus.RUNNING and not app.inspectors:
            app.results = []
            return

        app.results = [await run_inspector(spec, target) for spec in app.inspectors]

    # ----- rendering -------------------------------------------------------

    def _render(self) -> None:
        table = self.table
        self.rebuilding = True
        try:
            self._render_table()
        finally:
            self.rebuilding = False
        self._render_detail()

    def _render_table(self) -> None:
        table = self.table
        table.clear()
        dim = Text("·", style="dim")

        # The shipped catalogue covers ~100 engineering tools. Showing the ones
        # you don't have installed would bury the ones you do, so absent
        # entries are hidden unless asked for — they stay loaded either way, so
        # installing something later makes it appear on the next refresh.
        visible = [
            a
            for a in self.apps
            if self.config.show_absent or a.status is not AppStatus.ABSENT
        ]

        for app in sorted(
            visible, key=lambda a: (a.status is not AppStatus.RUNNING, a.name)
        ):
            match app.status:
                case AppStatus.RUNNING:
                    state = Text("active", style="bold")
                    cpu = Text(f"{app.proc.get('cpu', 0.0):.0f}" if app.proc else "0")
                    mem = Text(f"{app.proc.get('rss_mb', 0.0):,.0f}" if app.proc else "0")
                case AppStatus.INSTALLED:
                    state = Text("ready", style="dim")
                    cpu = mem = dim
                case _:
                    state = Text("absent", style="dim")
                    cpu = mem = dim

            table.add_row(
                Text(f"{app.glyph} {app.name}"), state, cpu, mem, key=app.id
            )

    def _render_detail(self) -> None:
        app = self._selected()
        if app is None:
            self.detail.update(Text("no selection", style="dim"))
            return

        text = Text()
        text.append(f"{app.name}\n", style="bold")
        text.append(f"{app.status.value}\n", style="dim")

        facts = process_facts(app.proc)
        if facts:
            text.append("\n")
            for key, value in facts:
                text.append(f"{key:<9}", style="dim")
                text.append(f"{value}\n")
        elif app.status is AppStatus.INSTALLED:
            text.append("\nnot running\n", style="dim")
        elif app.status is AppStatus.ABSENT:
            path = app.detect.get("bundle") or app.detect.get("path") or app.detect.get("which")
            text.append(f"\nnot found at\n{path}\n", style="dim")

        for result in app.results:
            text.append(f"\n{result.label}\n", style="bold")
            if not result.ok:
                text.append(f"  {result.note}\n", style="dim")
                continue
            for row in result.rows:
                text.append(f"  {row}\n")

        self.detail.update(text)

    # ----- commands --------------------------------------------------------

    def commands(self) -> Iterable[Command]:
        for app in self.apps:
            if app.status is AppStatus.ABSENT:
                continue

            if app.status is not AppStatus.RUNNING:
                if action := app.launch_action():
                    yield Command(
                        id=f"launchpad.open.{app.id}",
                        title=f"Launch {app.name}",
                        subtitle="not running",
                        action=action,
                        tags=("app", "launch", "open", app.id),
                    )

            if app.status is AppStatus.RUNNING and app.pid and self._platform:
                # Both verbs come from the Platform layer so each OS uses its
                # own polite path — on macOS that is System Events rather than
                # SIGTERM, which is what lets a GUI app show its save dialog.
                #
                # Quit and force-kill are always separate entries; nothing here
                # silently escalates one into the other.
                yield Command(
                    id=f"launchpad.quit.{app.id}",
                    title=f"Quit {app.name}",
                    subtitle=f"pid {app.pid} · asks the app to save first",
                    action=self._platform.quit_app(app.pid, app.os_name),
                    tags=("app", "quit", "close", app.id),
                )
                yield Command(
                    id=f"launchpad.kill.{app.id}",
                    title=f"Force-kill {app.name}",
                    subtitle=f"pid {app.pid} · unsaved work is lost",
                    action=self._platform.kill_app(app.pid, app.os_name),
                    tags=("app", "kill", "force", app.id),
                )

            for extra in app.actions:
                if argv := extra.get("exec"):
                    yield Command(
                        id=f"launchpad.{app.id}.{extra.get('key', 'x')}",
                        title=f"{app.name}: {extra.get('title', 'action')}",
                        subtitle=" ".join(argv)[:60],
                        action=Action(
                            extra.get("title", "action"),
                            list(argv),
                            Danger.SAFE,
                            detach=True,
                        ),
                        tags=("app", app.id),
                    )
