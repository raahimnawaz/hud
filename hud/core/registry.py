"""Plugin discovery: built-ins plus anything installed under the `hud.plugins`
entry-point group, so a third-party plugin is a pip install away.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from hud.core.config import Config
from hud.core.plugin import Plugin


def load_plugins(config: Config) -> list[Plugin]:
    from hud.plugins.launchpad import LaunchpadPlugin
    from hud.plugins.power import PowerPlugin
    from hud.plugins.projects import ProjectsPlugin

    plugins: list[Plugin] = [
        ProjectsPlugin(config),
        LaunchpadPlugin(config),
        PowerPlugin(),
    ]

    for ep in entry_points(group="hud.plugins"):
        try:
            plugins.append(ep.load()())
        except Exception:
            # A broken third-party plugin must not take the whole HUD down.
            continue

    return plugins
