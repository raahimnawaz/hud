"""Projects — the unit of work, not just a list of repos.

A project bundles a repo (or several), the apps it needs, its containers, and
its sim/PCB files, so that "start working on the gesture bot" is one action
rather than six windows.

Every git repo becomes a project automatically with its capabilities read off
disk (see detect.py), so the useful state is there before you configure
anything. `~/.config/hud/projects.yaml` exists to override or to combine
several repos into one project — never to get started.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass, field
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
from hud.plugins.hardware.kicad import build_bom, pick_root_schematic, read_board
from hud.plugins.projects.detect import Capabilities, detect

MAX_CONCURRENT_GIT = 8
GHOSTTY_BIN = "/Applications/Ghostty.app/Contents/MacOS/ghostty"


# --------------------------------------------------------------------- git --


@dataclass
class RepoState:
    path: Path
    branch: str = "?"
    ahead: int = 0
    behind: int = 0
    dirty: int = 0
    age_seconds: float | None = None
    error: str = ""
    is_repo: bool = True
    """A declared project need not be a git repo at all — a schematic folder
    or a sim scene is a perfectly good project. Those simply have no git row
    rather than showing a raw `fatal:` from git."""

    @property
    def name(self) -> str:
        return self.path.name


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    days = int(seconds // 86400)
    return f"{days}d" if days < 365 else f"{days // 365}y"


def _parse_status_v2(stdout: str) -> tuple[str, int, int, int]:
    """Returns (branch, ahead, behind, dirty_count).

    One `git status --porcelain=v2 --branch` yields all four, which keeps this
    at two subprocesses per repo instead of four.
    """
    branch, ahead, behind, dirty = "?", 0, 0, 0
    for line in stdout.splitlines():
        if not line:
            continue
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head ") :].strip()
        elif line.startswith("# branch.ab "):
            for part in line[len("# branch.ab ") :].split():
                if part.startswith("+"):
                    ahead = int(part[1:])
                elif part.startswith("-"):
                    behind = int(part[1:])
        elif not line.startswith("#"):
            dirty += 1
    return branch, ahead, behind, dirty


# ----------------------------------------------------------------- project --


@dataclass
class Project:
    id: str
    name: str
    root: Path
    repo_paths: list[Path] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    caps: Capabilities = field(default_factory=Capabilities)
    derived: bool = True
    """True when auto-discovered rather than declared in projects.yaml."""

    repos: list[RepoState] = field(default_factory=list)

    @property
    def dirty(self) -> int:
        return sum(r.dirty for r in self.repos if r.is_repo)

    @property
    def branch_summary(self) -> str:
        branches = {r.branch for r in self.repos if r.is_repo and not r.error}
        if not branches:
            return "—"
        return branches.pop() if len(branches) == 1 else f"{len(branches)} branches"

    @property
    def newest_age(self) -> float | None:
        ages = [r.age_seconds for r in self.repos if r.age_seconds is not None]
        return min(ages) if ages else None


def _terminal_action(title: str, cwd: Path, command: str | None = None) -> Action:
    """Open a terminal at `cwd`, optionally running `command` first.

    Note on ROS 2 overlays: `source install/setup.bash` only affects the shell
    that runs it, so it cannot be done "in the background" — it has to be part
    of the launched shell's command line, followed by an exec so the shell
    stays interactive.
    """
    if command:
        inner = f"cd {cwd!s:} && {command} && exec $SHELL"
    else:
        inner = f"cd {cwd!s:} && exec $SHELL"

    if Path(GHOSTTY_BIN).exists():
        argv = [GHOSTTY_BIN, "-e", "/bin/zsh", "-lc", inner]
    else:
        # Terminal.app has no argv form; AppleScript is the supported path.
        argv = ["osascript", "-e", f'tell application "Terminal" to do script "{inner}"']
    return Action(title, argv, Danger.SAFE, detach=True)


class ProjectsPanel(Vertical):
    """Master-detail: project list above, composite state below."""

    DEFAULT_CSS = """
    ProjectsPanel > DataTable {
        height: 45%;
        min-height: 6;
        scrollbar-size-horizontal: 0;
    }
    ProjectsPanel > #project-detail {
        height: 1fr;
        padding: 1 0 0 0;
        overflow-y: auto;
    }
    """

    def __init__(self, plugin: ProjectsPlugin) -> None:
        super().__init__()
        self._plugin = plugin

    def compose(self) -> ComposeResult:
        yield self._plugin.table
        yield self._plugin.detail

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Redrawing the table re-emits this event; without both guards the
        # redraw would request a refresh that redraws the table again.
        if self._plugin.rebuilding:
            return
        if event.row_key is None or event.row_key.value is None:
            return
        if self._plugin.select(str(event.row_key.value)):
            self._plugin.render_detail()


class ProjectsPlugin(BasePlugin):
    id = "projects"
    title = "projects"
    refresh_interval = 10.0

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.projects: list[Project] = []
        self.status = ""
        self.degraded = False
        self.selected_id: str | None = None
        self.rebuilding = False

        self.table = DataTable(cursor_type="row", zebra_stripes=False)
        self.table.add_columns("PROJECT", "BRANCH", "STATE", "STACK")
        self.detail = Static("", id="project-detail")
        self._panel = ProjectsPanel(self)

    def select(self, project_id: str) -> bool:
        if project_id == self.selected_id:
            return False
        self.selected_id = project_id
        return True

    def _selected(self) -> Project | None:
        if self.selected_id is not None:
            found = next((p for p in self.projects if p.id == self.selected_id), None)
            if found is not None:
                return found
        return self.projects[0] if self.projects else None

    # ----- discovery -------------------------------------------------------

    def _discover(self) -> list[Project]:
        """Auto-derive one project per git repo, then apply YAML overrides."""
        found: list[Project] = []
        seen_roots: set[Path] = set()

        for root in self.config.project_roots:
            if not root.is_dir():
                continue
            try:
                entries = sorted(p for p in root.iterdir() if p.is_dir())
            except (PermissionError, OSError):
                continue
            for entry in entries:
                if not (entry / ".git").exists():
                    continue
                seen_roots.add(entry)
                found.append(
                    Project(
                        id=entry.name,
                        name=entry.name,
                        root=entry,
                        repo_paths=[entry],
                        caps=detect(entry),
                    )
                )

        by_id = {p.id: p for p in found}

        for raw in self.config.projects:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            pid = raw["id"]
            root = Path(raw.get("root", "~")).expanduser()
            repos = [Path(r).expanduser() for r in raw.get("repos", [])] or [root]
            by_id[pid] = Project(
                id=pid,
                name=raw.get("name", pid),
                root=root,
                repo_paths=repos,
                apps=list(raw.get("apps", [])),
                caps=detect(root),
                derived=False,
            )

        return sorted(by_id.values(), key=lambda p: (p.derived, p.name))

    # ----- polling ---------------------------------------------------------

    async def refresh(self, target: Target) -> None:
        self.error = None
        self.projects = self._discover()

        if not self.projects:
            self.status = "no projects found"
            self.degraded = True
            self._render()
            return

        self.degraded = False
        sem = asyncio.Semaphore(MAX_CONCURRENT_GIT)

        async def inspect(path: Path) -> RepoState:
            async with sem:
                return await self._inspect(path, target)

        try:
            all_paths = [p for proj in self.projects for p in proj.repo_paths]
            states = await asyncio.gather(*(inspect(p) for p in all_paths))
        except Exception as exc:  # a provider must never take the app down
            self.error = f"scan failed: {exc}"
            self._render()
            return

        by_path = {s.path: s for s in states}
        for project in self.projects:
            project.repos = [by_path[p] for p in project.repo_paths if p in by_path]

        dirty = sum(1 for p in self.projects if p.dirty)
        self.status = f"{len(self.projects)} projects · {dirty} dirty"
        self._render()

    async def _inspect(self, path: Path, target: Target) -> RepoState:
        state = RepoState(path=path)

        status = await target.host.run(
            ["git", "-C", str(path), "status", "--porcelain=v2", "--branch"],
            timeout=8.0,
        )
        if not status.ok:
            stderr = (status.stderr or "").lower()
            if "not a git repository" in stderr:
                state.is_repo = False
            else:
                state.error = (status.stderr or "git failed").splitlines()[0][:40]
            return state

        state.branch, state.ahead, state.behind, state.dirty = _parse_status_v2(
            status.stdout
        )

        log = await target.host.run(
            ["git", "-C", str(path), "log", "-1", "--format=%ct"], timeout=8.0
        )
        if log.ok and log.stdout.strip().isdigit():
            state.age_seconds = max(0.0, time.time() - int(log.stdout.strip()))

        return state

    # ----- rendering -------------------------------------------------------

    def _render(self) -> None:
        self.rebuilding = True
        try:
            self._render_table()
        finally:
            self.rebuilding = False
        self.render_detail()

    def _render_table(self) -> None:
        table = self.table
        table.clear()
        for project in self.projects:
            if any(r.error for r in project.repos):  # real git failure
                state = Text("error", style="bold red")
            elif project.dirty:
                state = Text(f"✎ {project.dirty}", style="yellow")
            else:
                state = Text("clean", style="green")

            stack = ", ".join(project.caps.tags[:3]) or "·"
            table.add_row(
                Text(project.name, style="bold" if not project.derived else ""),
                Text(project.branch_summary),
                state,
                Text(stack, style="dim"),
                key=project.id,
            )

    def render_detail(self) -> None:
        self.detail.update(self.build_detail())

    def build_detail(self) -> Text:
        """Built as a return value rather than written straight to the widget,
        so the composite state can be asserted on without a running app."""
        project = self._selected()
        if project is None:
            return Text("no projects", style="dim")

        text = Text()
        text.append(f"{project.name}\n", style="bold")
        text.append(f"{project.root}\n", style="dim")

        for repo in project.repos:
            if not repo.is_repo:
                continue
            text.append("\n")
            text.append(f"{repo.name:<22}", style="")
            if repo.error:
                text.append(repo.error, style="red")
            else:
                text.append(f"{repo.branch}  ", style="dim")
                if repo.dirty:
                    text.append(f"✎{repo.dirty} ", style="yellow")
                if repo.ahead:
                    text.append(f"↑{repo.ahead} ", style="green")
                if repo.behind:
                    text.append(f"↓{repo.behind} ", style="red")
                text.append(_format_age(repo.age_seconds), style="dim")
            text.append("\n")

        caps = project.caps
        if caps.tags:
            text.append("\nSTACK\n", style="bold")
            for tag in caps.tags:
                text.append(f"  {tag}\n")

        if caps.ros_overlay:
            text.append("\nROS 2 OVERLAY\n", style="bold")
            text.append(f"  {caps.ros_overlay.relative_to(project.root)}\n", style="dim")
        if caps.compose:
            text.append("\nCOMPOSE\n", style="bold")
            text.append(f"  {caps.compose.name}\n", style="dim")
        if caps.sim_worlds:
            text.append("\nSIM WORLDS\n", style="bold")
            for world in caps.sim_worlds[:4]:
                text.append(f"  {world.name}\n", style="dim")
        if caps.schematics:
            root_sheet = pick_root_schematic(caps.schematics)
            if root_sheet is not None:
                self._render_bom(text, root_sheet)

        if caps.boards:
            info = read_board(caps.boards[0])
            text.append("\nBOARD\n", style="bold")
            if info.error:
                text.append(f"  {info.error}\n", style="dim")
            else:
                text.append(f"  {info.layers} copper layers · "
                            f"{info.footprints} footprints · {info.vias} vias\n")

        return text

    def _render_bom(self, text: Text, schematic: Path) -> None:
        """Inline BOM, parsed from the schematic directly — no KiCad needed."""
        bom = build_bom(schematic)
        text.append("\nBOM  ", style="bold")
        if bom.error:
            text.append(bom.error, style="dim")
            text.append("\n")
            return

        if bom.ready:
            text.append("ready", style="green")
        else:
            text.append(f"{len(bom.unfootprinted)} unfootprinted", style="yellow")
        text.append(
            f"   {bom.total_components} parts · {bom.unique_parts} unique"
            f" · {bom.sheets_read} sheet(s)\n",
            style="dim",
        )

        for line in bom.lines[:6]:
            text.append(f"  {line.quantity:>3}× ")
            text.append(f"{line.value[:18]:<18} ", style="")
            text.append(f"{line.refs_display[:22]}\n", style="dim")
        if len(bom.lines) > 6:
            text.append(f"      +{len(bom.lines) - 6} more lines\n", style="dim")

        if bom.unfootprinted:
            text.append(
                f"  missing footprints: {', '.join(bom.unfootprinted[:6])}\n",
                style="yellow",
            )

    # ----- commands --------------------------------------------------------

    def commands(self) -> Iterable[Command]:
        for project in self.projects:
            root = str(project.root)
            caps = project.caps

            # ENGAGE — the whole point. One entry that brings the workspace up
            # with its overlay sourced, rather than six manual steps.
            setup: list[str] = []
            if caps.ros_overlay:
                setup.append(f"source {caps.ros_overlay}")
            elif caps.venv:
                setup.append(f"source {caps.venv}/bin/activate")
            if caps.compose:
                setup.append(f"docker compose -f {caps.compose} up -d")

            yield Command(
                id=f"projects.engage.{project.id}",
                title=f"Engage {project.name}",
                subtitle=" · ".join(caps.tags) or "editor + shell",
                action=_terminal_action(
                    f"Engage {project.name}",
                    project.root,
                    " && ".join(setup) if setup else None,
                ),
                tags=("project", "engage", "start", project.id, root),
            )

            yield Command(
                id=f"projects.code.{project.id}",
                title=f"Open {project.name} in VS Code",
                subtitle=root,
                action=Action(
                    "Open in VS Code",
                    ["open", "-a", "Visual Studio Code", root],
                    Danger.SAFE,
                    detach=True,
                ),
                tags=("project", "code", "edit", project.id),
            )

            yield Command(
                id=f"projects.shell.{project.id}",
                title=f"Shell in {project.name}",
                subtitle=root,
                action=_terminal_action(f"Shell in {project.name}", project.root),
                tags=("project", "shell", "terminal", project.id),
            )

            if caps.compose:
                yield Command(
                    id=f"projects.up.{project.id}",
                    title=f"{project.name}: compose up",
                    subtitle=caps.compose.name,
                    action=Action(
                        f"{project.name} compose up",
                        ["docker", "compose", "-f", str(caps.compose), "up", "-d"],
                        Danger.CAUTION,
                    ),
                    tags=("project", "docker", "compose", project.id),
                )
                yield Command(
                    id=f"projects.down.{project.id}",
                    title=f"{project.name}: compose down",
                    subtitle="stops the project's containers",
                    action=Action(
                        f"{project.name} compose down",
                        ["docker", "compose", "-f", str(caps.compose), "down"],
                        Danger.DESTRUCTIVE,
                    ),
                    tags=("project", "docker", "compose", "stop", project.id),
                )

            for world in caps.sim_worlds[:4]:
                yield Command(
                    id=f"projects.sim.{project.id}.{world.stem}",
                    title=f"{project.name}: open {world.name}",
                    subtitle="Webots world",
                    action=Action(
                        f"Open {world.name}",
                        ["open", "-a", "Webots", str(world)],
                        Danger.SAFE,
                        detach=True,
                    ),
                    tags=("project", "sim", "webots", project.id),
                )

            yield Command(
                id=f"projects.reveal.{project.id}",
                title=f"Reveal {project.name} in Finder",
                subtitle=root,
                action=Action("Reveal", ["open", root], Danger.SAFE, detach=True),
                tags=("project", "finder", project.id),
            )
