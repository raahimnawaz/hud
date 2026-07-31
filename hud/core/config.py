"""Config loading. Everything user-editable lives in ~/.config/hud/.

apps.yaml is the piece that makes the launchpad generic: adding KiCad, a CAD
package, or anything else is a few lines of YAML and no Python.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("HUD_CONFIG_DIR", Path.home() / ".config" / "hud"))


@dataclass
class HostConfig:
    alias: str
    allow_power: bool = False
    label: str = ""


@dataclass
class Config:
    project_roots: list[Path] = field(default_factory=lambda: [Path.home()])
    project_depth: int = 1
    theme: str = "lattice"
    sphere_fps: int = 20
    skip_boot: bool = False
    show_absent: bool = False
    """Absent apps are hidden by default. The shipped catalogue covers ~100
    engineering tools; showing the ones you don't have installed would bury
    the ones you do. They stay loaded either way, so installing a tool later
    makes it appear on the next refresh with no config change."""
    catalogs: list[str] = field(default_factory=lambda: ["*"])
    hosts: list[HostConfig] = field(default_factory=list)
    apps: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    """Declared projects. Optional — every git repo is auto-derived into one,
    so this exists to override or to combine several repos, never to start."""

    @classmethod
    def load(cls) -> Config:
        cfg = cls()

        settings = CONFIG_DIR / "config.toml"
        if settings.is_file():
            data = tomllib.loads(settings.read_text())
            general = data.get("general", {})
            cfg.theme = general.get("theme", cfg.theme)
            cfg.sphere_fps = general.get("sphere_fps", cfg.sphere_fps)
            cfg.skip_boot = general.get("skip_boot", cfg.skip_boot)
            cfg.show_absent = general.get("show_absent", cfg.show_absent)
            cfg.catalogs = general.get("catalogs", cfg.catalogs)

            projects = data.get("projects", {})
            if roots := projects.get("roots"):
                cfg.project_roots = [Path(r).expanduser() for r in roots]
            cfg.project_depth = projects.get("depth", cfg.project_depth)

            for alias, host in data.get("hosts", {}).items():
                cfg.hosts.append(
                    HostConfig(
                        alias=alias,
                        allow_power=host.get("allow_power", False),
                        label=host.get("label", ""),
                    )
                )

        cfg.projects = _load_yaml_list(CONFIG_DIR / "projects.yaml")
        cfg.apps = _load_catalogs(cfg.catalogs) + _load_yaml_list(CONFIG_DIR / "apps.yaml")

        # A user entry with the same id as a catalogue entry wins, so you can
        # override a shipped path without editing the catalogue itself.
        merged: dict[str, dict[str, Any]] = {}
        for entry in cfg.apps:
            if isinstance(entry, dict) and entry.get("id"):
                merged[entry["id"]] = entry
        cfg.apps = list(merged.values())

        return cfg


def _load_yaml_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        loaded = yaml.safe_load(path.read_text()) or []
    except yaml.YAMLError:
        # A malformed catalogue must not take the HUD down with it.
        return []
    return loaded if isinstance(loaded, list) else []


def _load_catalogs(names: list[str]) -> list[dict[str, Any]]:
    """Load the shipped per-domain catalogues.

    `["*"]` loads them all, which is the default: detection is cheap, absent
    tools are hidden, and it means installing something later just makes it
    appear. Name specific domains to narrow it (e.g. ["robotics", "eda"]).
    """
    # Packaged copy first (works for `uvx hud-console`), repo copy second
    # (works when running from a clone without installing).
    package_dir = Path(__file__).resolve().parent.parent / "catalog"
    repo_dir = Path(__file__).resolve().parent.parent.parent / "catalog"
    catalog_dir = package_dir if package_dir.is_dir() else repo_dir
    if not catalog_dir.is_dir():
        return []

    if names == ["*"]:
        files = sorted(catalog_dir.glob("*.yaml"))
    else:
        files = [catalog_dir / f"{n}.yaml" for n in names]

    entries: list[dict[str, Any]] = []
    for path in files:
        entries.extend(_load_yaml_list(path))
    return entries


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR
