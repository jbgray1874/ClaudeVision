"""The shop does not laminate; the merchant does.

11908-21's trays are drawn as 9mm MDF with a LAMINATED finish — the DXFs are named
"9mm MDF+ LAM" and the route demanded a `laminating` operation nothing could price. The
run costed plain MDF at £1.35/kg (£43.12 a sheet against the £172 laminated board Tony
actually buys from Lawcris) and then flagged the laminate as "being supplied free" —
a 4x under-charge wearing a real-looking price, plus an ask to price work that belongs
in the material line.

Tony Ford, 16 Sep 2026: "Wrong sheet size for Laminated board / Wrong price for board".
James: "we can't copy it. We need to understand and learn from it" — so what is recorded
is the METHOD (a laminated core is bought pre-faced, by the sheet) and the one dated,
sourced price point, in the same register SDI's other purchased board prices live in.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


# ── the promotion needs evidence, never the material name alone ─────────────────────────

def test_a_laminating_op_promotes_mdf_to_the_faced_family():
    from estimator import _faced_board_promotion
    part = {"part_number": "11908-21-01J", "textual_operations": ["laminating"]}
    family, why = _faced_board_promotion(part, "MDF")
    assert family == "MFMDF"
    assert "laminating" in why


def test_the_cut_files_own_name_is_evidence():
    from estimator import _faced_board_promotion
    part = {"part_number": "11908-21-01J",
            "dxf_source_file": "11908-21-01J_9mm MDF+ LAM_REV[A].DXF"}
    family, why = _faced_board_promotion(part, "MDF")
    assert family == "MFMDF"


def test_plain_mdf_stays_plain_mdf():
    from estimator import _faced_board_promotion
    assert _faced_board_promotion({"part_number": "X"}, "MDF") == (None, "")


def test_an_already_faced_family_is_not_promoted_again():
    from estimator import _faced_board_promotion
    part = {"textual_operations": ["laminating"]}
    assert _faced_board_promotion(part, "MFMDF") == (None, "")
    assert _faced_board_promotion(part, "MELAMINE FACED MDF") == (None, "")


def test_a_laminated_chipboard_core_promotes_to_mfc():
    from estimator import _faced_board_promotion
    part = {"normalized_finish": "LAMINATED BOTH SIDES"}
    family, _ = _faced_board_promotion(part, "CHIPBOARD")
    assert family == "MFC"


# ── the money: the purchased sheet, never the raw core's kilos ───────────────────────────

def test_the_tray_base_prices_off_the_laminated_sheet():
    import estimator
    part = {"part_number": "11908-21-01J", "normalized_material": "MDF",
            "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
            "blank_width_mm": 390.0, "quantity": 2,
            "textual_operations": ["laminating"]}
    out = estimator.estimate_material(part)
    # THE IDENTITY SURVIVES THE PRICE BEING WITHDRAWN (D-103). Tony's own £172 is no
    # longer in config — it was his figure off his own estimate — but everything the
    # engine had to work out to USE it is still right: the board is a pre-faced laminate,
    # it belongs to the MFMDF family and not to plain MDF, and the sheet it is bought as
    # is a 3080x1220. Those are what his "wrong sheet size" complaint was about, and they
    # do not depend on knowing the money.
    assert out.get("costing_material_family") == "MFMDF"
    assert part.get("_laminate_in_board") is True
    assert any("bought pre-faced" in f for f in part.get("review_flags", []))
    assert out.get("cost_method") == "faced_board_unpriced", out.get("cost_method")
    assert not out.get("sheet_price_gbp"), (
        "a price typed into config is back — the 9mm point was Tony's own figure off his "
        "own sheet, which is what D-078 forbids")


def test_a_modelled_weight_does_not_put_the_board_back_on_core_kilos():
    """The 09:57 book: the trays carry a modelled weight, the stated-weight branch
    returned plain-MDF £/kg before the promotion ever ran, and the board shipped at
    £43.12-a-sheet money again. The weight stays on the record; its PRICING yields to
    the purchased sheet."""
    import estimator
    part = {"part_number": "11908-21-01J", "normalized_material": "MDF",
            "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
            "blank_width_mm": 390.0, "quantity": 2,
            "dxf_weight_kg": 1.03,
            "textual_operations": ["laminating"]}
    out = estimator.estimate_material(part)
    # THE PROTECTION THIS TEST EXISTS FOR IS UNCHANGED BY THE PRICE GOING. A modelled
    # weight must not send a pre-faced board back to plain-MDF kilo money — £43.12 a
    # sheet against a board that is bought laminated. It must land on the purchased-sheet
    # basis, and where that basis has no money yet it says so by name rather than
    # quietly reverting to the wrong one.
    assert out.get("cost_method") == "faced_board_unpriced", out.get("cost_method")
    assert "kg" not in str(out.get("cost_method") or "").lower()


def test_a_plain_board_with_a_weight_still_prices_by_its_weight():
    import estimator
    part = {"part_number": "X-01", "normalized_material": "MDF",
            "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
            "blank_width_mm": 390.0, "quantity": 1,
            "dxf_weight_kg": 1.03}
    out = estimator.estimate_material(part)
    assert out.get("cost_method") != "board_sheet_yield", \
        "no laminate evidence — the stated-weight path keeps its job"


def test_a_promoted_board_with_no_rate_never_falls_back_to_core_kilos():
    """No purchase point covers 50mm: outside the observed range is REFUSED, never
    extrapolated — and the part must go out unpriced and loud, because plain-core kilo
    money on a laminated panel is the same 4x under-charge at any thickness."""
    import estimator
    part = {"part_number": "X-01J", "normalized_material": "MDF",
            "normalized_thickness_mm": 50.0, "blank_length_mm": 390.0,
            "blank_width_mm": 390.0, "quantity": 1,
            "textual_operations": ["laminating"]}
    out = estimator.estimate_material(part)
    assert out.get("cost_method") == "faced_board_unpriced", out.get("cost_method")
    assert out.get("unit_material_cost_gbp") is None
    assert any("FACED BOARD UNPRICED" in f for f in part.get("review_flags", []))


# ── and the finish flag: charged in the board is not supplied free ───────────────────────

def _summary_with(part):
    return {"manufacturing_writeup": {"parts": [part]},
            "estimate_summary": {"part_estimates": [part],
                                 "final_estimate": {"labour_rows": []}}}


def test_a_laminate_bought_on_the_board_is_not_called_supplied_free():
    from invariants import check_a_stated_finish_is_costed
    part = {"part_number": "11908-21-01J", "normalized_finish": "LAMINATED",
            "_laminate_in_board": True,
            "material_estimate": {"cost_method": "board_sheet_yield",
                                  "costing_material_family": "MFMDF"}}
    out = check_a_stated_finish_is_costed(_summary_with(part))
    assert not [v for v in out if v.get("code") == "stated_finish_not_costed"], out


def test_a_laminate_on_plain_costed_board_still_fires():
    from invariants import check_a_stated_finish_is_costed
    part = {"part_number": "11908-21-01J", "normalized_finish": "LAMINATED",
            "material_estimate": {"cost_method": "per_kg"}}
    out = check_a_stated_finish_is_costed(_summary_with(part))
    assert [v for v in out if v.get("code") == "stated_finish_not_costed"], \
        "an unpromoted laminate is still uncosted work and must be flagged"
