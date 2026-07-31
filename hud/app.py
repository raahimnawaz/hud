"""HudApp — the shell that hosts plugins, the sphere, and the palette."""

from __future__ import annotations

from typing import Iterable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer

from hud.core.action import Action, Command, Danger
from hud.core.config import Config
from hud.core.confirm import ConfirmScreen
from hud.core.palette import HudCommands
from hud.core.plugin import Plugin
from hud.core.registry import load_plugins
from hud.core.runner import PowerDenied, gate_for, run_action
from hud.core.target import TargetRegistry
from hud.themes import ACCENTS, THEMES
from hud.widgets.boot import BootLine, BootScreen
from hud.widgets.frame import BracketFrame
from hud.widgets.readout import CoreReadout
from hud.widgets.sphere import CoreSphere, SphereState


class HudApp(App):
    CSS_PATH = "hud.tcss"
    COMMANDS = App.COMMANDS | {HudCommands}

    TITLE = "HUD"
    """Sets the terminal window title, which is how the Hammerspoon hotkey
    finds the HUD window to toggle rather than launching a second one."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("r", "refresh_all", "Refresh"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("ctrl+p", "command_palette", "Commands", show=True),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self.config_data = config or Config.load()
        self.targets = TargetRegistry.with_local()
        self.plugins: list[Plugin] = []
        self._sphere: CoreSphere | None = None
        self._readout: CoreReadout | None = None
        self._polling = 0
        # Not `_timers` — that name belongs to Textual's MessagePump.
        self._plugin_timers: list = []
        """Plugin refresh timers, held so they can be paused while hidden."""

    # ----- composition -----------------------------------------------------

    def compose(self) -> ComposeResult:
        self.plugins = load_plugins(self.config_data)
        accent = ACCENTS.get(self.config_data.theme, "#00d9ff")

        with Horizontal(id="grid"):
            with BracketFrame("core", id="core-panel"):
                self._sphere = CoreSphere(fps=self.config_data.sphere_fps, accent=accent)
                yield self._sphere
                self._readout = CoreReadout()
                yield self._readout

            for plugin in self.plugins:
                if plugin.panel() is None:
                    continue
                yield BracketFrame(plugin.title, id=f"panel-{plugin.id}")

        yield Footer()

    def __init_boot_lines(self) -> list[BootLine]:
        """Each line resolves against real state, so a missing catalogue or an
        unreachable host is visible here rather than discovered later."""
        target = self.targets.local
        n_apps = len(self.config_data.apps)
        n_roots = len(self.config_data.project_roots)
        panels = sum(1 for p in self.plugins if p.panel() is not None)

        return [
            BootLine("INITIALIZING PLUGIN REGISTRY", detail=f"{len(self.plugins)} loaded"),
            BootLine("PROBING LOCAL TARGET", detail=target.platform.id),
            BootLine(
                "LOADING APPLICATION CATALOGUE",
                resolve="OK" if n_apps else "EMPTY",
                detail=f"{n_apps} entries" if n_apps else "check apps.yaml",
                ok=bool(n_apps),
            ),
            BootLine("MAPPING PROJECT ROOTS", detail=f"{n_roots} root(s)"),
            BootLine("MOUNTING PANELS", detail=f"{panels} active"),
            BootLine("CORE ONLINE", resolve="██"),
        ]

    def on_mount(self) -> None:
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = self.config_data.theme

        if not self.config_data.skip_boot:
            self.push_screen(
                BootScreen(
                    self.__init_boot_lines(),
                    accent=ACCENTS.get(self.theme, "#00d9ff"),
                    fps=self.config_data.sphere_fps,
                )
            )

        # Panels are mounted after compose so each plugin's widget lands inside
        # its frame rather than beside it. Scheduling is deliberately separate
        # from mounting: a palette-only plugin (power) has no panel but still
        # needs to refresh, or it contributes no commands.
        for plugin in self.plugins:
            panel = plugin.panel()
            if panel is not None:
                self.query_one(f"#panel-{plugin.id}", BracketFrame).mount(panel)

            self._plugin_timers.append(
                self.set_interval(
                    plugin.refresh_interval,
                    lambda p=plugin: self.refresh_plugin(p),
                )
            )
            self.refresh_plugin(plugin)

        if self._readout is not None:
            target = self.targets.local
            self._readout.set_facts(
                [
                    ("TARGET", "local"),
                    ("SYSTEM", target.platform.id),
                    ("PLUGINS", str(len(self.plugins))),
                ]
            )

    # ----- plugin driving --------------------------------------------------

    def refresh_plugin(self, plugin: Plugin) -> None:
        self.run_worker(self._refresh_worker(plugin), exclusive=False, group=plugin.id)

    async def _refresh_worker(self, plugin: Plugin) -> None:
        self._set_polling(1)
        try:
            await plugin.refresh(self.targets.local)
        finally:
            self._set_polling(-1)

        frames = self.query(f"#panel-{plugin.id}")
        if not frames:
            return
        level = "error" if plugin.error else "ok"
        status = plugin.error or getattr(plugin, "status", "")
        if getattr(plugin, "degraded", False) and not plugin.error:
            level = "degraded"
        frames.first(BracketFrame).set_status(status, level=level)

    def _set_polling(self, delta: int) -> None:
        """The sphere spins up while any plugin is polling, so a refresh is
        something you can see rather than something you assume happened."""
        self._polling = max(0, self._polling + delta)
        if self._sphere is None:
            return
        if self._sphere.state in (SphereState.ERROR, SphereState.POWER_ARMED):
            return
        self._sphere.set_state(
            SphereState.POLLING if self._polling else SphereState.IDLE
        )

    def set_sphere_state(self, state: SphereState) -> None:
        if self._sphere is not None:
            self._sphere.set_state(state)

    def on_app_blur(self) -> None:
        """The HUD lives hidden behind a hotkey most of the time.

        Both the animation *and* the polling stop when it is not on screen.
        Stopping only the sphere is not enough — scanning every process and
        shelling out to inspectors for data nobody is reading was still
        costing ~10% of a core while hidden.
        """
        if self._sphere is not None:
            self._sphere.pause()
        for timer in self._plugin_timers:
            timer.pause()

    def on_app_focus(self) -> None:
        if self._sphere is not None:
            self._sphere.resume()
        for timer in self._plugin_timers:
            timer.resume()
        # Summoning the HUD should show current state, not whatever was true
        # when you last dismissed it.
        self.action_refresh_all()

    # ----- commands --------------------------------------------------------

    def all_commands(self) -> Iterable[Command]:
        for plugin in self.plugins:
            yield from plugin.commands()

    def dispatch_command(self, command: Command) -> None:
        if command.action is None:
            return
        self.run_worker(self._dispatch(command.action), exclusive=False)

    async def _dispatch(self, action: Action) -> None:
        target = action.target or self.targets.local
        gate, phrase = gate_for(action.danger, target)

        if gate != "none":
            if action.danger is Danger.DESTRUCTIVE:
                self.set_sphere_state(SphereState.POWER_ARMED)
            confirmed = await self.push_screen_wait(
                ConfirmScreen(action, gate, phrase=phrase)
            )
            self.set_sphere_state(SphereState.IDLE)
            if not confirmed:
                self.notify("Cancelled", severity="information")
                return

        self.set_sphere_state(SphereState.ACTION)
        try:
            result = await run_action(action, target)
        except PowerDenied as exc:
            self.set_sphere_state(SphereState.ERROR)
            self.notify(str(exc), severity="error", timeout=10)
            return

        if result.ok:
            self.notify(f"{action.title} — done")
        else:
            detail = (result.stderr or result.stdout).strip()[:200]
            self.notify(
                f"{action.title} failed: {detail}", severity="error", timeout=10
            )

        for plugin in self.plugins:
            self.refresh_plugin(plugin)

    # ----- actions ---------------------------------------------------------

    def action_refresh_all(self) -> None:
        for plugin in self.plugins:
            self.refresh_plugin(plugin)

    def action_cycle_theme(self) -> None:
        names = [t.name for t in THEMES]
        idx = names.index(self.theme) if self.theme in names else 0
        self.theme = names[(idx + 1) % len(names)]

    def watch_theme(self, theme: str) -> None:
        if self._sphere is not None and theme in ACCENTS:
            self._sphere.set_accent(ACCENTS[theme])
