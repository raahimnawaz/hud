"""Capability detection for a project root.

The design goal is zero configuration: every git repo becomes a usable project
immediately, because what a project *is* can be read off the filesystem. A
`docker-compose.yml` means it has containers. An `install/setup.bash` means it
is a ROS 2 workspace. A `.wbt` under `worlds/` means it has a Webots scene.

Users only write YAML when they want to override or combine — never to get
started. That is what keeps the flow short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Checked in order; first hit wins for single-valued fields.
COMPOSE_NAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
VENV_NAMES = (".venv", "venv", "env")
ROS_OVERLAY = Path("install") / "setup.bash"

MAX_GLOB_HITS = 12
"""Scanning is bounded: a project with 4000 meshes should not cost 4000 stats
just to show that it has sim files."""


@dataclass
class Capabilities:
    """What a project root can do, read off disk."""

    compose: Path | None = None
    ros_overlay: Path | None = None
    venv: Path | None = None
    cmake: bool = False
    sim_worlds: list[Path] = field(default_factory=list)
    kicad_projects: list[Path] = field(default_factory=list)
    schematics: list[Path] = field(default_factory=list)
    boards: list[Path] = field(default_factory=list)
    notebooks: int = 0

    @property
    def tags(self) -> list[str]:
        """Short labels for the panel — the at-a-glance summary."""
        out: list[str] = []
        if self.ros_overlay:
            out.append("ros2")
        if self.compose:
            out.append("compose")
        if self.venv:
            out.append("venv")
        if self.cmake:
            out.append("cmake")
        if self.sim_worlds:
            out.append(f"sim×{len(self.sim_worlds)}")
        if self.schematics or self.kicad_projects:
            out.append(f"pcb×{max(len(self.schematics), len(self.kicad_projects))}")
        if self.notebooks:
            out.append(f"nb×{self.notebooks}")
        return out


def _bounded_glob(root: Path, pattern: str) -> list[Path]:
    hits: list[Path] = []
    try:
        for path in root.glob(pattern):
            hits.append(path)
            if len(hits) >= MAX_GLOB_HITS:
                break
    except (OSError, PermissionError):
        pass
    # glob order is filesystem order, which is not stable across machines.
    return sorted(hits)


def detect(root: Path) -> Capabilities:
    """Inspect a project root. Never raises; an unreadable tree yields empty."""
    caps = Capabilities()
    if not root.is_dir():
        return caps

    for name in COMPOSE_NAMES:
        candidate = root / name
        if candidate.is_file():
            caps.compose = candidate
            break

    overlay = root / ROS_OVERLAY
    if overlay.is_file():
        caps.ros_overlay = overlay

    for name in VENV_NAMES:
        candidate = root / name
        if (candidate / "bin" / "activate").is_file():
            caps.venv = candidate
            break

    caps.cmake = (root / "CMakeLists.txt").is_file()

    # Webots scenes conventionally live in worlds/, but not always.
    caps.sim_worlds = _bounded_glob(root, "worlds/*.wbt") or _bounded_glob(root, "*.wbt")
    caps.kicad_projects = _bounded_glob(root, "*.kicad_pro") or _bounded_glob(
        root, "*/*.kicad_pro"
    )
    # Schematics and boards are found independently of the .kicad_pro: a repo
    # may carry sources without the project file, and the BOM only needs the
    # schematic.
    caps.schematics = _bounded_glob(root, "*.kicad_sch") or _bounded_glob(
        root, "*/*.kicad_sch"
    )
    caps.boards = _bounded_glob(root, "*.kicad_pcb") or _bounded_glob(
        root, "*/*.kicad_pcb"
    )
    caps.notebooks = len(_bounded_glob(root, "*.ipynb")) + len(
        _bounded_glob(root, "notebooks/*.ipynb")
    )

    return caps
