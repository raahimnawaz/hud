"""Per-app inspectors — the "what is this app actually doing" layer.

Two sources, and the split matters:

1. **Process facts** are universal and free. PID, uptime, thread count, memory,
   CPU. Every running app gets these with no configuration at all.

2. **Declarative inspectors** are per-app and live in apps.yaml, so a new app's
   detail view needs no Python. `docker ps`, `kicad-cli version`, `code
   --list-extensions` — anything with a CLI can report into the panel.

Cost discipline: inspectors run for the *selected* app only, on their own
interval. Running every app's inspector on every poll would mean shelling out
to a dozen CLIs every few seconds for output nobody is looking at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hud.core.target import Target


@dataclass(frozen=True)
class InspectSpec:
    """One declarative probe, from the `inspect:` block of an app entry."""

    label: str
    argv: list[str]
    parse: str = "lines"
    """lines | count | first | raw"""
    max_rows: int = 6
    empty: str = "—"
    timeout: float = 5.0

    @classmethod
    def from_yaml(cls, raw: dict[str, Any]) -> InspectSpec | None:
        argv = raw.get("exec")
        if not argv:
            return None
        return cls(
            label=raw.get("label", "INFO"),
            argv=list(argv),
            parse=raw.get("parse", "lines"),
            max_rows=int(raw.get("max", 6)),
            empty=raw.get("empty", "—"),
            timeout=float(raw.get("timeout", 5.0)),
        )


@dataclass
class InspectResult:
    label: str
    rows: list[str] = field(default_factory=list)
    ok: bool = True
    note: str = ""
    """Set when the probe could not run — a dead daemon, a missing binary.
    This is displayed as dim text, never as an error: an app whose CLI is not
    available is a normal state, not a fault."""


def _humanize_uptime(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{seconds // 86400}d {seconds % 86400 // 3600}h"


def process_facts(proc_info: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Universal facts available for any running process, no config needed."""
    if not proc_info:
        return []

    facts: list[tuple[str, str]] = [("pid", str(proc_info["pid"]))]

    if (cpu := proc_info.get("cpu")) is not None:
        facts.append(("cpu", f"{cpu:.1f}%"))
    if (rss := proc_info.get("rss_mb")) is not None:
        facts.append(("memory", f"{rss:,.0f} MB"))
    if (threads := proc_info.get("threads")) is not None:
        facts.append(("threads", str(threads)))
    if (created := proc_info.get("created")) is not None:
        facts.append(("uptime", _humanize_uptime(time.time() - created)))

    return facts


def _normalize_error(raw: str) -> str:
    """Turn a CLI's error spew into one calm phrase.

    A daemon that isn't running is the single most common case and its native
    message is a wall of socket paths. Truncating that mid-path — which the
    first version did — produces a garbled fragment that looks like a bug in
    the HUD rather than a stopped service.
    """
    text = (raw or "").strip()
    if not text:
        return "unavailable"

    first = text.splitlines()[0].strip()
    low = first.lower()

    if "connect" in low and any(
        k in low for k in ("docker", "daemon", "socket", "/var/run", ".sock")
    ):
        return "daemon not running"
    if "timed out" in low:
        return first
    if "command not found" in low or "no such file" in low:
        return "not on PATH"
    if "permission denied" in low:
        return "permission denied"

    for prefix in ("error during connect:", "cannot connect to", "error:", "fatal:"):
        if low.startswith(prefix):
            first = first[len(prefix):].strip()
            break

    if len(first) <= 46:
        return first
    # Cut on a word boundary so the result reads as a sentence, not a fragment.
    return first[:46].rsplit(" ", 1)[0] + "…"


async def run_inspector(spec: InspectSpec, target: Target) -> InspectResult:
    """Execute one probe. Never raises — a failed probe is a note, not a fault."""
    result = InspectResult(label=spec.label)

    completed = await target.host.run(spec.argv, timeout=spec.timeout)

    if not completed.ok:
        result.ok = False
        result.note = _normalize_error(completed.stderr or completed.stdout)
        return result

    lines = [ln.rstrip() for ln in completed.stdout.splitlines() if ln.strip()]

    match spec.parse:
        case "count":
            result.rows = [str(len(lines))]
        case "first":
            result.rows = lines[:1] or [spec.empty]
        case "raw":
            result.rows = lines[: spec.max_rows]
        case _:  # lines
            result.rows = lines[: spec.max_rows]
            if len(lines) > spec.max_rows:
                result.rows.append(f"… +{len(lines) - spec.max_rows} more")

    if not result.rows:
        result.rows = [spec.empty]
        result.ok = True

    return result
