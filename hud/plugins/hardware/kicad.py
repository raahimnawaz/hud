"""KiCad schematic and board reading — BOM and manufacturing readiness.

Reads `.kicad_sch` and `.kicad_pcb` directly (see sexpr.py) rather than driving
`kicad-cli`, so a design can be inspected on a machine that has no KiCad
installed. That also makes it fast enough to run inline in the TUI: no process
spawn, no GUI toolkit load.

Hierarchical sheets are followed, because a real design is rarely one file and
a BOM that silently covers only the root sheet is worse than no BOM.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from hud.plugins.hardware.sexpr import (
    SExprError,
    children,
    find_all,
    head,
    loads,
    unquote,
)

MAX_SHEET_DEPTH = 8
"""Hierarchical designs nest; a cyclic sheet reference must not hang the UI."""


@dataclass
class Component:
    reference: str
    value: str
    footprint: str
    lib_id: str = ""

    @property
    def is_power(self) -> bool:
        """Power symbols (#PWR, #FLG) are annotations, not purchasable parts.

        Excluding them is the difference between a BOM you can order from and
        one an assembler will bounce back.
        """
        return self.reference.startswith("#")

    @property
    def unfootprinted(self) -> bool:
        return not self.footprint.strip()


@dataclass
class BomLine:
    value: str
    footprint: str
    references: list[str] = field(default_factory=list)

    @property
    def quantity(self) -> int:
        return len(self.references)

    @property
    def refs_display(self) -> str:
        return ", ".join(sorted(self.references, key=_ref_sort_key))


@dataclass
class Bom:
    source: Path
    lines: list[BomLine] = field(default_factory=list)
    total_components: int = 0
    unfootprinted: list[str] = field(default_factory=list)
    sheets_read: int = 1
    error: str = ""

    @property
    def unique_parts(self) -> int:
        return len(self.lines)

    @property
    def ready(self) -> bool:
        """Manufacturing readiness in one flag: every part has a footprint."""
        return not self.unfootprinted and not self.error


def _ref_sort_key(ref: str) -> tuple[str, int]:
    """R10 sorts after R9, not between R1 and R2."""
    prefix = ref.rstrip("0123456789")
    digits = ref[len(prefix) :]
    return prefix, int(digits) if digits.isdigit() else 0


def _properties(symbol_node) -> dict[str, str]:
    """KiCad stores fields as (property "Name" "Value" ...)."""
    props: dict[str, str] = {}
    for prop in children(symbol_node, "property"):
        if len(prop) >= 3:
            props[unquote(prop[1])] = unquote(prop[2])
    return props


def _lib_id(symbol_node) -> str:
    for node in children(symbol_node, "lib_id"):
        if len(node) >= 2:
            return unquote(node[1])
    return ""


def read_schematic(path: Path, _depth: int = 0, _seen: set[Path] | None = None):
    """Return (components, sheets_read). Follows hierarchical sheets."""
    seen = _seen if _seen is not None else set()
    resolved = path.resolve()
    if resolved in seen or _depth > MAX_SHEET_DEPTH:
        return [], 0
    seen.add(resolved)

    try:
        tree = loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SExprError):
        return [], 0

    components: list[Component] = []
    sheets = 1

    # Top-level placed symbols only. `lib_symbols` holds library *definitions*,
    # which are not instances and must not be counted.
    for node in tree if isinstance(tree, list) else []:
        if not isinstance(node, list) or head(node) != "symbol":
            continue
        props = _properties(node)
        ref = props.get("Reference", "")
        if not ref:
            continue
        components.append(
            Component(
                reference=ref,
                value=props.get("Value", ""),
                footprint=props.get("Footprint", ""),
                lib_id=_lib_id(node),
            )
        )

    # Hierarchical sub-sheets carry a "Sheetfile" property.
    for sheet in find_all(tree, "sheet"):
        props = _properties(sheet)
        filename = props.get("Sheetfile") or props.get("Sheet file")
        if not filename:
            continue
        child_path = path.parent / filename
        if child_path.is_file():
            sub, sub_sheets = read_schematic(child_path, _depth + 1, seen)
            components.extend(sub)
            sheets += sub_sheets

    return components, sheets


def build_bom(path: Path) -> Bom:
    """Aggregate a schematic into an orderable BOM."""
    bom = Bom(source=path)

    components, sheets = read_schematic(path)
    if not components and sheets == 0:
        bom.error = "unreadable or not a schematic"
        return bom

    bom.sheets_read = max(1, sheets)
    real = [c for c in components if not c.is_power]
    bom.total_components = len(real)

    grouped: dict[tuple[str, str], BomLine] = {}
    for comp in real:
        key = (comp.value, comp.footprint)
        line = grouped.get(key)
        if line is None:
            line = BomLine(value=comp.value, footprint=comp.footprint)
            grouped[key] = line
        line.references.append(comp.reference)
        if comp.unfootprinted:
            bom.unfootprinted.append(comp.reference)

    bom.lines = sorted(
        grouped.values(), key=lambda l: (-l.quantity, l.value.lower())
    )
    bom.unfootprinted.sort(key=_ref_sort_key)
    return bom


def pick_root_schematic(paths: list[Path]) -> Path | None:
    """Choose the top sheet from a set of schematics.

    A hierarchical design has one root and N sub-sheets, and picking wrong
    silently produces a BOM covering a fragment of the board. Filesystem order
    is no guide, so this resolves it structurally: the root is the sheet that
    no other sheet references via its `Sheetfile` property.
    """
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]

    ordered = sorted(paths)
    referenced: set[Path] = set()

    for path in ordered:
        try:
            tree = loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SExprError):
            continue
        for sheet in find_all(tree, "sheet"):
            props = {}
            for prop in children(sheet, "property"):
                if len(prop) >= 3:
                    props[unquote(prop[1])] = unquote(prop[2])
            filename = props.get("Sheetfile") or props.get("Sheet file")
            if filename:
                referenced.add((path.parent / filename).resolve())

    roots = [p for p in ordered if p.resolve() not in referenced]
    return roots[0] if roots else ordered[0]


@dataclass
class BoardInfo:
    source: Path
    layers: int = 0
    footprints: int = 0
    nets: int = 0
    vias: int = 0
    error: str = ""


def read_board(path: Path) -> BoardInfo:
    """Summarise a .kicad_pcb — enough to sanity-check before ordering."""
    info = BoardInfo(source=path)
    try:
        tree = loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SExprError):
        info.error = "unreadable or not a board"
        return info

    for layers_node in find_all(tree, "layers"):
        # Copper layers are the ones that cost money; each entry is
        # (0 "F.Cu" signal) style.
        info.layers = sum(
            1
            for entry in layers_node[1:]
            if isinstance(entry, list)
            and len(entry) >= 2
            and unquote(entry[1]).endswith(".Cu")
        )
        break

    info.footprints = sum(1 for _ in find_all(tree, "footprint"))
    info.vias = sum(1 for _ in find_all(tree, "via"))
    info.nets = max(0, sum(1 for _ in find_all(tree, "net")) - 1)  # net 0 is no-net
    return info
