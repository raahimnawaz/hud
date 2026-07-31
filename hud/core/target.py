"""A Target pairs a Host (where) with a Platform (how).

This is the one abstraction the whole design rests on: because the two are
independent, the same three Platform backends serve local execution and remote
execution. Portability and remote control stop being separate projects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hud.core.host import Host, LocalHost, SSHHost
from hud.core.platform import Platform, local_platform


@dataclass
class Target:
    host: Host
    platform: Platform
    online: bool = True
    detail: str = ""
    """Why the target is offline, when it is."""

    @property
    def label(self) -> str:
        if self.host.is_local:
            return f"this machine ({self.platform.id})"
        return f"{self.host.alias} ({self.platform.id})"

    @property
    def allows_power(self) -> bool:
        """Remote hosts must be explicitly opted into power control."""
        if self.host.is_local:
            return True
        return getattr(self.host, "allow_power", False)

    def mark_offline(self, detail: str = "") -> None:
        """Shutting down a host drops our own connection to it. That is the
        expected outcome of a successful action, not an error to surface.
        """
        self.online = False
        self.detail = detail


@dataclass
class TargetRegistry:
    targets: dict[str, Target] = field(default_factory=dict)

    @classmethod
    def with_local(cls) -> TargetRegistry:
        local = Target(host=LocalHost(), platform=local_platform())
        return cls(targets={"local": local})

    @property
    def local(self) -> Target:
        return self.targets["local"]

    async def add_ssh(self, alias: str, *, allow_power: bool = False) -> Target | None:
        """Probe a remote host and register it if reachable.

        Returns None when the host cannot be identified — an unreachable box
        should show as OFFLINE in the UI, not raise into it.
        """
        host = SSHHost(alias=alias, allow_power=allow_power)
        platform_id = await host.probe()
        if platform_id is None:
            target = Target(
                host=host,
                platform=local_platform(),
                online=False,
                detail="unreachable",
            )
            self.targets[alias] = target
            return None

        from hud.core.platform import PLATFORMS

        target = Target(host=host, platform=PLATFORMS[platform_id])
        self.targets[alias] = target
        return target
