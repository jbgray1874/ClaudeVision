r"""A rate for the bare core is not a rate for the board that was bought.

James Gray, 17 September 2026, on the 15:18 11908-21 book:

    "Laminated MDF is still costed as raw MDF: 3050 x 1525 at £43.12, not the faced-board
     family and its 3080 x 1220 stock size. That repeats Tony's 'wrong sheet size / wrong
     board price' finding... Bench Work is at 30/hr, not the scoped 2/hr; Packing Joinery
     is 75/hr, not his 20/hr. Both indicate the job is still classified as plain MDF, so
     the faced-board pilot is not reaching the workbook.

     One main technical root: the `MDF+ LAM` evidence is not promoting the live parts into
     the faced-board family. That one failure explains the raw board price, wrong stock
     sheet, missing scoped joinery rates, and much of the labour mismatch."

WHY IT PASSED EVERY TEST AND FAILED EVERY RUN. The promotion worked. Eleven tests drove it
and it promoted 11908-21's trays every time — because in a test there is no database. The
live run asks the UDEF catalogue for a £/m² on the material as READ, finds plain 9mm MDF,
prices the part by area and RETURNS, four hundred lines above the faced-board block. The
promotion was unreachable on any board SDI actually stocks, and nothing could see it:
the unit tests exercised a branch the live path never arrived at.

That is the two-roads fault again, on the pricing side rather than the labour side. So the
promotion is asked ONCE, in front of every pricing path, and the catalogue is asked about
the board on the purchase order:

    PROMOTED, AND THE CATALOGUE HAS THE FACED FAMILY    priced from it — rung 1, current
    PROMOTED, AND IT DOES NOT                           unpriced and visible; never the core's
    NOT PROMOTED                                        exactly as before

The control at the bottom is the half that must not move: plain MDF with no laminate
evidence still prices from the live catalogue rate, as it has all along.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402

# The tray, as the live pack presents it: material read as MDF, the laminate carried by the
# cut file's own name — "11908-21-01J_9mm MDF+ LAM_REV[A].dxf".
_TRAY = {"part_number": "11908-21-01J", "normalized_material": "MDF",
         "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2,
         "dxf_source_file": "11908-21-01J_9mm MDF+ LAM_REV[A].DXF"}


def _tray(**over):
    return dict(_TRAY, **over)


class _Catalogue:
    """Stands in for UDEF. Answers for the material tokens it was given, nothing else."""

    def __init__(self, **rates):
        self.rates = {k.upper(): v for k, v in rates.items()}
        self.asked = []

    def __call__(self, material, thickness_mm):
        token = str(material or "").upper()
        self.asked.append(token)
        rate = self.rates.get(token)
        if rate is None:
            return None
        return {"rate_gbp_per_m2": float(rate), "thickness_mm": thickness_mm,
                "material_token": token, "sample_count": 3, "basis": "test_catalogue"}


def _with_catalogue(monkeypatch, cat):
    monkeypatch.setattr(estimator, "_resolve_board_sheet_rate_gbp_per_m2", cat)
    return cat


# ── the defect, reproduced ───────────────────────────────────────────────────────────

def test_a_plain_mdf_catalogue_rate_does_not_price_a_laminated_tray(monkeypatch):
    """£9.27/m² of plain 9mm MDF is £43.12 across a 3050 x 1525 — the exact figure on
    Tony's sheet. It is a real, current, checkable rate for a board this job does not buy."""
    cat = _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    out = estimator.estimate_material(_tray())
    assert out.get("cost_method") != "sheet_rate_live_udef", (
        "the bare core's catalogue rate priced a pre-faced board")
    assert out.get("costing_material_family") == "MFMDF"
    assert "MFMDF" in cat.asked, "the catalogue was never asked about the board being bought"


def test_the_promotion_survives_the_catalogue(monkeypatch):
    """The stamp the rest of the engine reads. Without it the workbook's scoped joinery
    rates see a plain-MDF job and run on the department guesses Tony corrected."""
    part = _tray()
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    estimator.estimate_material(part)
    assert part.get("_laminate_in_board") is True
    assert any("bought pre-faced" in str(f) for f in part.get("review_flags", []))


def test_it_is_unpriced_and_loud_rather_than_cheap_and_quiet(monkeypatch):
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    part = _tray()
    out = estimator.estimate_material(part)
    assert out.get("cost_method") == "faced_board_unpriced", out.get("cost_method")
    assert out.get("unit_material_cost_gbp") is None
    assert any("FACED BOARD UNPRICED" in str(f) for f in part.get("review_flags", []))


def test_the_sheet_it_reports_is_the_faced_family_s(monkeypatch):
    """Tony's "wrong sheet size" in one assertion: 3050 x 1525 is plain MDF's stock, and
    the board is not plain MDF."""
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    out = estimator.estimate_material(_tray())
    sheet = (out.get("stock_estimate") or {}).get("candidate_sheet_size_mm") or []
    assert list(sheet) != [3050.0, 1525.0] and list(sheet) != [3050, 1525], sheet
    assert tuple(sheet) in {(2800, 2070), (3080, 1220), (2440, 1220),
                            (2800.0, 2070.0), (3080.0, 1220.0), (2440.0, 1220.0)}, sheet


# ── and where the catalogue DOES hold the board, that is the best answer there is ────

def test_a_live_faced_rate_is_used_and_named(monkeypatch):
    """Rung 1: SDI's own current catalogue, for the board on the purchase order. Nothing
    in this engine beats it and nothing here invents it — if UDEF holds MFMDF, it wins."""
    cat = _with_catalogue(monkeypatch, _Catalogue(MDF=9.27, MFMDF=37.50))
    out = estimator.estimate_material(_tray())
    assert out.get("cost_method") == "sheet_rate_live_udef"
    assert out.get("costing_material_family") == "MFMDF"
    # 0.39 x 0.39 = 0.1521 m2 at £37.50 = £5.70, plus scrap — and nowhere near core money.
    assert out.get("cost_per_part_gbp") > 5.0, out.get("cost_per_part_gbp")


def test_the_faced_rate_is_nested_on_the_faced_family_s_sheet(monkeypatch):
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27, MFMDF=37.50))
    out = estimator.estimate_material(_tray())
    sheet = (out.get("stock_estimate") or {}).get("candidate_sheet_size_mm") or []
    assert list(sheet) != [3050.0, 1525.0], "nested on plain MDF's sheet"


# ── the control: nothing that worked may move ────────────────────────────────────────

def test_plain_mdf_still_prices_from_the_live_catalogue(monkeypatch):
    """No laminate anywhere on the record — same part, same rate, the behaviour that has
    been right all along."""
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    out = estimator.estimate_material(
        {"part_number": "X-01", "normalized_material": "MDF",
         "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2,
         "dxf_source_file": "X-01_9mm MDF_REV[A].DXF"})
    assert out.get("cost_method") == "sheet_rate_live_udef", out.get("cost_method")
    assert out.get("costing_material_family") == "MDF"


def test_the_evidence_is_still_required(monkeypatch):
    """"MDF" and a catalogue rate do not make a faced board. The promotion needs the
    drawing to say so — a laminating op, a finish, a file name, a description."""
    from estimator import _faced_board_promotion
    assert _faced_board_promotion({"part_number": "X-01"}, "MDF") == (None, "")


def test_the_evidence_flag_is_raised_once(monkeypatch):
    """The promotion is asked in front of the catalogue AND the sheet-yield block reads
    its answer. Asking twice would put the same sentence on the line twice."""
    _with_catalogue(monkeypatch, _Catalogue(MDF=9.27))
    part = _tray()
    estimator.estimate_material(part)
    said = [f for f in part.get("review_flags", []) if "bought pre-faced" in str(f)]
    assert len(said) == 1, said
