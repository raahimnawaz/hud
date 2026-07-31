"""Where a command runs. Orthogonal to *how* it is expressed (see platform.py).

Security note on SSHHost: this module deliberately knows nothing about
credentials. It never prompts for a password, parses a key, or stores a secret.
It shells out to the system `ssh` binary with a `~/.ssh/config` alias and lets
OpenSSH handle authentication against the user's agent. That is both the most
secure design available and the least code.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from hud.core.action import Completed


@runtime_checkable
class Host(Protocol):
    """A place commands can be executed."""

    alias: str
    is_local: bool

    async def run(self, argv: list[str], timeout: float = 10.0) -> Completed: ...

    async def spawn(self, argv: list[str]) -> None:
        """Start a process and do not wait for it (GUI launches)."""
        ...


@dataclass
class LocalHost:
    """This machine. argv is passed through exec directly — no shell involved."""

    alias: str = "local"
    is_local: bool = True

    async def run(self, argv: list[str], timeout: float = 10.0) -> Completed:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return Completed(returncode=127, stderr=str(exc))

        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return Completed(returncode=124, stderr=f"timed out after {timeout}s")

        return Completed(
            returncode=proc.returncode or 0,
            stdout=out.decode(errors="replace"),
            stderr=err.decode(errors="replace"),
        )

    async def spawn(self, argv: list[str]) -> None:
        try:
            await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except (FileNotFoundError, PermissionError, OSError):
            # Callers surface launch failure via the detect poll flipping back
            # to INSTALLED rather than RUNNING; nothing to raise into the UI.
            pass


@dataclass
class SSHHost:
    """Another machine, reached through the system ssh client.

    `alias` must be a Host entry in ~/.ssh/config. We store an alias and nothing
    else — no hostname, no username, no credential. Connection detail belongs in
    OpenSSH's config, where the user already manages it.

    ControlMaster multiplexing is not an optimization here, it is a requirement:
    a polling TUI would otherwise pay a full handshake (~200-500ms) on every
    refresh and hammer the remote sshd with auth events.
    """

    alias: str
    is_local: bool = False
    allow_power: bool = False
    """Opt-in per host. A host cannot be powered off until explicitly enabled."""

    ssh_options: list[str] = field(
        default_factory=lambda: [
            "-o", "BatchMode=yes",           # never hang on an interactive prompt
            "-o", "StrictHostKeyChecking=accept-new",  # never 'no'
            "-o", "ConnectTimeout=5",
            "-o", "ControlMaster=auto",
            "-o", "ControlPath=~/.ssh/cm-%r@%h:%p",
            "-o", "ControlPersist=10m",
            "-o", "ServerAliveInterval=15",
        ]
    )

    def _wrap(self, argv: list[str]) -> list[str]:
        """Build the local argv that runs `argv` on the remote.

        ssh hands its command to the remote *login shell*, so the remote side is
        a shell context whether we want one or not. Every element gets quoted —
        repo paths and YAML-sourced app names are untrusted input.
        """
        remote = " ".join(shlex.quote(a) for a in argv)
        return ["ssh", *self.ssh_options, self.alias, "--", remote]

    async def run(self, argv: list[str], timeout: float = 10.0) -> Completed:
        return await LocalHost().run(self._wrap(argv), timeout=timeout)

    async def spawn(self, argv: list[str]) -> None:
        await LocalHost().spawn(self._wrap(argv))

    async def probe(self) -> str | None:
        """Identify the remote OS so a Platform can be paired with this host.

        Returns 'macos' | 'linux' | 'windows' | None (unreachable).
        """
        result = await self.run(["uname", "-s"], timeout=8.0)
        if result.ok:
            kernel = result.stdout.strip().lower()
            if "darwin" in kernel:
                return "macos"
            if "linux" in kernel:
                return "linux"
        # No uname: likely a Windows shell rather than WSL.
        result = await self.run(["cmd", "/c", "ver"], timeout=8.0)
        if result.ok and "windows" in result.stdout.lower():
            return "windows"
        return None
