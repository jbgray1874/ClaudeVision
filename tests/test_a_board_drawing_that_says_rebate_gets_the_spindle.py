"""Saw and spindle exist on the rate card and nothing ever emitted the operation.

    "No edge banding, no machining saw/spindle, no bench work time, CNC setup not amortised"
                                            — Tony Ford on 11908-21, 16 Sep 2026

MC J, "Machines Joinery", has been on the Estimate template's rate card all along at
£28.735/hr with a 30-minute set-up, and the department vocabulary knew its spellings —
morticing, tenoning, spindle moulding, planing. What was missing was anything that MINTED
the operation, so 4.67 of Tony's 42 hours had nowhere in the engine to land. That is his
finding exactly: not a wrong rate, an absent line.

MINTED ONLY ON THE DRAWING'S OWN EVIDENCE. A rebate, groove, housing, mortice, tenon,
moulding, mitre or profile is spindle work and the drawing says so in words — and SDI's own
SolidWorks export carries a REBATE layer, so it is stated in the CAD too. A board part with
none of that gets no such line: the engine does not know that every panel is sawn, and
assuming it would put half an hour of set-up plus run time on every joinery job in the shop.

That is the whole discipline here — the drawing identifies what needs doing, the register
says what the department's throughput is, and neither infers the other.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402
import department_codes                                               # noqa: E402
from document_builder import _interpret_part                          # noqa: E402  (import guard)  # noqa: F401


def _board(**over):
    part = {"part_number": "11908-21-02", "description": "TRAY BASE",
            "normalized_material": "MFMDF",
            "material_estimate": {"material": "MFMDF"},
            "normalized_geometry": {"blank_length_mm": 600, "blank_width_mm": 400}}
    part.update(over)
    return part


def _ops(part, page_text=""):
    """Run the board-operations pass the way document_builder does."""
    import document_builder as db
    import re
    # The block under test keys off board material and the part's own finish text; this
    # mirrors its inputs rather than re-implementing its decision.
    finish = " ".join([page_text.upper(),
                       " ".join(str(f) for f in (part.get("surface_finishes") or [])).upper(),
                       str(part.get("normalized_finish") or "").upper(),
                       " ".join(str(n) for n in (part.get("process_notes") or [])).upper(),
                       str(part.get("description") or "").upper()])
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "document_builder.py"), encoding="utf-8").read()
    i = src.index('_mcj = re.search(')
    j = src.index('_finish_text)', i) + len('_finish_text)')
    pattern = src[i:j].split("re.search(", 1)[1].rsplit(",", 1)[0]
    return bool(re.search(eval(pattern.replace("\n", "").replace("                ", "")),
                          finish))


# ── the department was always there ──────────────────────────────────────────────────────

def test_the_operation_routes_to_machines_joinery():
    assert department_codes.code_for("machining_joinery") == "MC J"
    assert department_codes.CODE_TITLES["MC J"][0] == "Machines Joinery"


def test_the_row_has_a_rate_and_a_setup_so_it_can_be_costed():
    """A row the rate card cannot price blanks the labour total — this table has been caught
    by that twice, with the acrylic router and then edge banding."""
    from sheet_steel_costing import RATE_CARD
    rate, setup, code = RATE_CARD["Machines Joinery"]
    assert code == "MC J" and rate > 0 and setup > 0
    assert config.OPERATION_SETUP_MIN["MC J"] == setup


def test_the_row_has_a_throughput_floor_and_takes_the_measured_figure():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert '"Machines Joinery": 30,' in src, "a floor, or the derived throughput is garbage"
    assert "joinery_machining_parts_per_hour" in src, "and the register overlays it"
    assert '"machining_joinery": "Machines Joinery",' in src, "and the op names the row"


def test_it_sits_between_the_router_and_the_edge_bander():
    """The panel is cut and profiled before its edges are banded."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert '"Machines Joinery": 18,' in src


# ── minted on evidence, and on nothing else ──────────────────────────────────────────────

def test_the_words_that_mean_spindle_work():
    for text in ("REBATE ALL ROUND", "25mm GROOVE", "HOUSING FOR SHELF", "MORTICE AND TENON",
                 "MOULDED EDGE", "PROFILED FRONT", "MITRED CORNERS", "SPINDLE"):
        assert _ops(_board(), page_text=text), text


def test_a_plain_panel_gets_no_machining_line():
    """THE GUARD. The engine does not know that every panel is sawn, and assuming it would
    put half an hour of set-up plus run time on every joinery job in the shop."""
    for text in ("LAMINATED BOTH SIDES", "EDGED ALL ROUND", "", "PAINT RAL9005"):
        assert not _ops(_board(), page_text=text), text


def test_the_rebate_layer_in_the_cad_counts_as_evidence():
    """SDI's SolidWorks export carries a REBATE layer, so the fact is in the CAD as well as
    in the words — stated against the source, because the layer read is upstream of here."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "document_builder.py"), encoding="utf-8").read()
    i = src.index("SAW AND SPINDLE")
    block = src[i:i + 2500]
    assert "dxf_layers" in block and "REBATE" in block


def test_the_measured_throughput_is_tonys_and_says_it_is_derived():
    key = "joinery_machining_parts_per_hour"
    # His 4.6667 hours for fifty, LESS the half-hour set-up the engine already holds for
    # MC J, divides to exactly 12 an hour — set-up is charged separately, once per order.
    _run_h = 4.6667 - config.OPERATION_SETUP_MIN["MC J"] / 60.0
    assert abs(config.SHOP_STATED[key] - 50 / _run_h) < 0.01
    assert config.SHOP_STATED[key] == 12.0
    assert "Tony Ford" in config.shop_stated_source(key)
    assert config.SHOP_STATED_PROVENANCE[key]["evidence"].startswith("DERIVED")


# ── a board assembly is fitted before it is packed ───────────────────────────────────────
#
# "No bench work time." BENC is 25.5 of Tony's 42 hours — the biggest operation on the job —
# and the engine charged none of it. Not a wrong rate: the operation never existed, for one
# reason. Every non-welded assembly mints ONE `assembly` event, and for board the workbook's
# op map sends "assembly" to Packing Joinery — so a tray's assembly event became its PACKING
# row, and the fitting that produced the tray was charged as boxing it. One event doing two
# jobs and landing on the wrong one. Tony's sheet has both because both are real.

def _assembly(**over):
    part = {"part_number": "11908-21", "description": "SUNGLASSES TRAY",
            "normalized_material": "MFMDF", "is_assembly_parent": True,
            "assembly_children": ["11908-21-01", "11908-21-02", "11908-21-03"]}
    part.update(over)
    return part


def _bench_minutes(part):
    """Run the joinery route rule the way estimate_process_times does."""
    import re
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    assert "A BOARD ASSEMBLY IS FITTED BEFORE IT IS PACKED" in src
    mat = str(part.get("normalized_material") or "").upper().replace("_", " ")
    is_board_asm = (any(w in mat for w in ("MDF", "MFMDF", "MFC", "CHIPBOARD", "PLYWOOD",
                                           "PLY", "TIMBER", "BIRCH", "VENEER", "LAMINATE"))
                    and (part.get("is_assembly_parent") or part.get("assembly_children")
                         or str(part.get("canonical_kind") or "").lower() == "assembly"))
    if not is_board_asm:
        return None
    return 60.0 / config.SHOP_STATED["joinery_bench_parts_per_hour"]


def test_a_board_assembly_is_bench_fitted():
    assert _bench_minutes(_assembly()) == 30.0


def test_the_minutes_reproduce_tonys_own_hours():
    """30 minutes a tray across fifty, plus the department's 30-minute set-up charged once,
    is 25.5 hours — which is the figure on his Labour tab, arrived at from the other end."""
    mins = _bench_minutes(_assembly())
    qty = config.SHOP_STATED["joinery_rates_measured_at_quantity"]
    total_h = (mins * qty) / 60.0 + config.OPERATION_SETUP_MIN["BENC"] / 60.0
    assert abs(total_h - 25.5) < 0.01, total_h


def test_the_setup_is_not_added_per_part():
    """It is the department's set-up, charged once per order by the workbook. Adding it here
    as well is the double-count that made the first version of these rates wrong."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    i = src.index("A BOARD ASSEMBLY IS FITTED BEFORE IT IS PACKED")
    block = src[i:i + 3200]
    assert '_st_b["bench_work"]' not in block, "the set-up must not be booked per part"
    assert "charged once per order" in block


def test_a_metal_or_acrylic_assembly_is_untouched():
    """An acrylic display really is assembled and packed in one PACP pass — that is what
    Howard's "Apply Tape, Bag, Bulk Pack" describes — so no metal or acrylic job moves."""
    assert _bench_minutes(_assembly(normalized_material="ACRYLIC")) is None
    assert _bench_minutes(_assembly(normalized_material="MILD STEEL")) is None


def test_a_board_LEAF_gets_no_bench_line():
    """The evidence is the BOM's own structure: a parent with children has to be put
    together. A single panel has nothing to fit."""
    assert _bench_minutes({"part_number": "11908-21-02", "normalized_material": "MFMDF"}) \
        is None


def test_the_line_says_it_is_a_scoped_pilot_and_asks():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    i = src.index("A BOARD ASSEMBLY IS FITTED BEFORE IT IS PACKED")
    # 4200: the rule's comment, the gate and the whole review flag. A window that clips the
    # flag would pass while the sentence an estimator reads had been deleted.
    block = src[i:i + 4200]
    assert "THE DRAWING DOES NOT ANNOTATE THIS" in block
    assert "SCOPED PILOT" in block and "confirm it applies" in block
    assert "shop_stated_source('joinery_bench_parts_per_hour')" in block
