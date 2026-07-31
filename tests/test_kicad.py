"""Schematic parser tests.

These are the tests worth having in CI: they depend on nothing about the
machine running them — no KiCad, no GUI, no network — so they prove the claim
that a BOM can be extracted from a design on a host that has never had KiCad
installed.

The fixture is a hierarchical two-sheet design carrying every case that
separates an orderable BOM from one an assembler bounces back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hud.plugins.hardware.kicad import build_bom, pick_root_schematic
from hud.plugins.hardware.sexpr import SExprError, loads, unquote

FIXTURES = Path(__file__).parent / "fixtures"
MAIN = FIXTURES / "main.kicad_sch"
POWER = FIXTURES / "power.kicad_sch"


# ----------------------------------------------------------------- sexpr --


def test_parses_nested_lists():
    tree = loads("(a (b c) (d (e f)))")
    assert tree[0] == "a"
    assert tree[1] == ["b", "c"]
    assert tree[2] == ["d", ["e", "f"]]


def test_quoted_strings_are_distinguishable_from_atoms():
    # KiCad property values are always quoted; symbol names never are. The
    # parser must not collapse the two or `(value 1k)` and `(value "1k")`
    # become indistinguishable.
    tree = loads('(prop "1k" 1k)')
    assert unquote(tree[1]) == "1k"
    assert tree[2] == "1k"
    assert tree[1] != tree[2]


def test_escaped_quotes_inside_strings():
    tree = loads(r'(property "Value" "4k7 \"precision\"")')
    assert unquote(tree[2]) == '4k7 "precision"'


@pytest.mark.parametrize("bad", ["(a", "a)", '(a "unterminated', ""])
def test_malformed_input_raises_rather_than_corrupting(bad):
    with pytest.raises(SExprError):
        loads(bad)


# ------------------------------------------------------------------- bom --


def test_root_sheet_is_resolved_structurally():
    """Filesystem order must not decide which sheet is the root.

    Picking a sub-sheet silently yields a BOM for a fragment of the board.
    """
    assert pick_root_schematic([POWER, MAIN]) == MAIN
    assert pick_root_schematic([MAIN, POWER]) == MAIN


def test_hierarchical_sheets_are_followed():
    bom = build_bom(MAIN)
    assert bom.sheets_read == 2
    refs = {r for line in bom.lines for r in line.references}
    assert {"C2", "U2"} <= refs, "sub-sheet parts missing from BOM"


def test_power_symbols_are_excluded():
    bom = build_bom(MAIN)
    refs = {r for line in bom.lines for r in line.references}
    assert not any(r.startswith("#") for r in refs)
    assert "#PWR01" not in refs and "#PWR02" not in refs


def test_lib_symbols_definitions_are_not_counted_as_instances():
    # `lib_symbols` holds library definitions, which carry a Reference
    # property ("R") but are not placed parts.
    bom = build_bom(MAIN)
    refs = {r for line in bom.lines for r in line.references}
    assert "R" not in refs
    assert bom.total_components == 7


def test_identical_parts_group_across_sheets():
    bom = build_bom(MAIN)
    hundred_nf = next(l for l in bom.lines if l.value == "100nF")
    assert hundred_nf.quantity == 2
    assert sorted(hundred_nf.references) == ["C1", "C2"]


def test_references_sort_numerically():
    """R10 sorts after R2, not between R1 and R2."""
    bom = build_bom(MAIN)
    resistors = next(l for l in bom.lines if l.value == "10k")
    assert resistors.refs_display == "R1, R2"


def test_missing_footprints_block_manufacturing_readiness():
    bom = build_bom(MAIN)
    assert bom.unfootprinted == ["U1"]
    assert bom.ready is False


def test_unreadable_file_degrades_rather_than_raising(tmp_path):
    junk = tmp_path / "broken.kicad_sch"
    junk.write_text("this is not an s-expression")
    bom = build_bom(junk)
    assert bom.error
    assert bom.lines == []


def test_missing_file_degrades(tmp_path):
    bom = build_bom(tmp_path / "nope.kicad_sch")
    assert bom.error
