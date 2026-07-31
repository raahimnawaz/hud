"""Aggregates every plugin's commands into Textual's built-in command palette.

Extending the built-in palette rather than building a bespoke one means fuzzy
matching, highlighting, and keyboard handling come for free — and theme
switching stays in the same list as plugin actions.
"""

from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider


class HudCommands(Provider):
    """Palette entries contributed by the loaded plugins."""

    async def startup(self) -> None:
        self._commands = list(self.app.all_commands())

    async def discover(self) -> Hits:
        """Shown before the user types anything — the safe, common entries."""
        for cmd in self._commands[:24]:
            yield DiscoveryHit(
                cmd.title,
                partial(self.app.dispatch_command, cmd),
                help=cmd.subtitle or None,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for cmd in self._commands:
            haystack = " ".join((cmd.title, cmd.subtitle, *cmd.tags)).strip()
            score = matcher.match(haystack)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(cmd.title),
                    partial(self.app.dispatch_command, cmd),
                    help=cmd.subtitle or None,
                )
