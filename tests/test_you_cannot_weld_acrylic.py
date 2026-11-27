r"""
test_you_cannot_weld_acrylic.py

12349-02's 01A came back with Weld (CO2) and Dress Welds on it. The drawing says UV BONDED and
Tim's sheet has no weld on that part at all — it is seven acrylic pieces glued into a box.

WELD (CO2) is an arc, a filler wire and a bead somebody then grinds flat. Put an acrylic panel
under it and there is no part left. This is not a rate to tune; it is a physical
impossibility, so it is corrected rather than flagged and left costing.

Weld becomes Glue — the operation that actually joins these parts, and one the rate card
carries. Dressing is dropped outright: a bonded joint has no bead to dress, and the row would
charge a hand pass for work nobody does.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sheet_steel_costing as ssc                                   # noqa: E402
import wb_populate as wb                                            # noqa: E402

SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


def _guard() -> str:
    i = SRC.index("# YOU CANNOT WELD ACRYLIC.")
    return SRC[i:i + 2600]


def test_glue_is_a_department_the_rate_card_carries():
    """A substitution onto a name the table does not have LOOKUPs to zero — the row appears,
    costs nothing, and reads exactly like work nobody found."""
    assert "Glue" in ssc.RATE_CARD
    assert ssc.RATE_CARD["Glue"][0] > 0


@pytest.mark.parametrize("dept", ["Weld (CO2)", "Spotweld"])
def test_a_weld_on_acrylic_becomes_a_bond(dept):
    g = _guard()
    assert f'"{dept}"' in g, f"{dept} is not caught"
    assert 'wb_op = "Glue"' in g


def test_dressing_a_bond_is_dropped_not_repriced():
    g = _guard()
    i = g.index('if wb_op == "Dress Welds":')
    assert "continue" in g[i:i + 400], "the row is still costed"


def test_steel_is_untouched():
    """The guard is gated on the part being acrylic. A welded steel bracket must be unaffected
    — this engine's welding is most of its labour."""
    g = _guard()
    assert "if _is_acr" in g, "the guard is not gated on the material at all"


def test_timber_is_excluded_too():
    """_is_board lumps timber in with acrylic, so _is_acr is true for MDF. A timber part is
    not bonded acrylic and must not be swept up by an acrylic rule — the same conflation that
    put 'Assemble/pack (Acrylic)' against 3mm MDF."""
    assert "not _is_timber(_mat)" in _guard()


def test_the_substitution_is_said_out_loud():
    """A silent correction of the customer's own route is worse than the error: only an
    estimator can confirm the joint is a bond."""
    g = _guard()
    assert "_flag(" in g and "acrylic is bonded, not" in g


def test_the_guard_runs_after_the_operation_has_a_department():
    """It tests wb_op, so it has to sit after the mapping and after the None fallback —
    ordering here is the whole of whether it fires."""
    tree = ast.parse(SRC)
    mapped = SRC.index("wb_op = _map_operation(op, _is_acr, _sf or \"\", _mat)")
    fallback = SRC.index('_flag(f"labour op \'{op}\' ({_pn}) not in OP_NAME_MAP')
    guard = SRC.index("# YOU CANNOT WELD ACRYLIC.")
    assert mapped < fallback < guard
    assert isinstance(tree, ast.Module)
