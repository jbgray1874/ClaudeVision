r"""
test_the_priceable_reading_rescues_an_unpriceable_winner.py

THE RANK-WINNING VALUE IS NOT ALWAYS THE COSTABLE ONE.

Arbitration ranks sources by how well they know what a part IS. It says nothing about
whether this engine holds a rate for the answer. On 11650-01-05A DOOR those came apart:

    solidworks_api        rank 90   ABS             no sheet gate, no GBP/kg  -> UNPRICEABLE
    drawing text          rank 70   POLYCARBONATE   GBP 21.70/m2 at 6mm       -> priceable

A 1202 x 689 x 6mm door -- laser cut, drilled and assembled, every one of those costed --
carried GBP 0.00 of material. The estimate was short by about GBP 18.69 and nothing on the
sheet, in the reports or in the checks said a word.

Three things this must not do, and each has a test below.

It must not change normalized_material. What the part IS stays the arbitration's answer; a
lower-ranked source does not win a datum by being convenient, and the reports must keep
showing what the model said.

It must not improve a total quietly. The substitution is recorded and reported as a conflict
an estimator rules on. A number that appears with no explanation is the failure this whole
layer exists to stop.

It must not fire when the winner is priceable. This is a rescue for an unpriceable winner,
not a preference for whichever reading is cheapest.

And the silence is reported either way: rescued or not, a material with no rate is OUR gap --
no input an estimator can supply creates a rate the engine does not have.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                        # noqa: E402
import invariants as inv                                             # noqa: E402
from invariants import BLOCKING, WARNING, UNVERIFIED                 # noqa: E402
from estimator import _material_we_can_actually_price as price_from  # noqa: E402


# ── the predicate, against the real tables ──────────────────────────────────────────
@pytest.mark.parametrize("material,expected", [
    ("ABS", False),                 # the door. No gate entry, no GBP/kg.
    ("POLYCARBONATE", True),        # both
    ("ACRYLIC", True),
    ("HIPS", True),                 # gate only -- the m2 path always resolves via "default"
    ("MILD STEEL", True),
    ("MILD_STEEL", True),           # underscore spelling
    ("mild steel", True),           # case
    ("", False), (None, False), ("UNOBTAINIUM", False),
])
def test_whether_a_rate_exists_at_all(material, expected):
    assert config.material_has_a_rate(material) is expected


def test_the_costing_gate_and_the_predicate_are_one_set():
    """The gate was a set literal inside estimate_material where nothing could ask it. A
    second copy would drift from the tables it describes."""
    import ast
    body = ast.unparse(ast.parse((ROOT / "src" / "estimator.py").read_text(encoding="utf-8")))
    assert "config.PLASTIC_SHEET_PRICED_MATERIALS" in body
    assert '"PERSPEX", "PMMA", "POLYCARBONATE"' not in body, "the inline literal is back"


# ── the rescue ──────────────────────────────────────────────────────────────────────
def _door():
    return {"part_number": "11650-01-05A", "normalized_material": "ABS",
            "materials": ["POLYCARBONATE"]}


def test_an_unpriceable_winner_is_priced_from_a_reading_that_has_a_rate():
    material, conflict = price_from(_door(), "ABS")
    assert material == "POLYCARBONATE"
    assert conflict["arbitrated_material"] == "ABS"
    assert conflict["priced_material_source"] == "drawing text"


def _real_door():
    """The door as estimate_material actually receives it."""
    return {"part_number": "11650-01-05A", "normalized_material": "ABS",
            "materials": ["POLYCARBONATE"], "quantity": 1, "normalized_thickness_mm": 6,
            "normalized_geometry": {"blank_length_mm": 1202, "blank_width_mm": 689}}


def test_the_arbitrated_material_is_not_overwritten():
    """THROUGH estimate_material, NOT THE HELPER. Two mutants survived a version of this
    test that called _material_we_can_actually_price directly: the overwrite and the
    recording both happen in the CALLER, so testing the helper proved nothing about either.
    The trap wb_populate's own comment names -- test the caller, not the helper.

    estimate_material writes the canonical family back to normalized_material so
    wb_populate's block routing sees it. Substituting BEFORE that line sent the rescue
    material through it, silently replacing arbitration's answer with the reading that
    merely happened to have a rate.
    """
    from estimator import estimate_material
    part = _real_door()
    estimate_material(part)
    assert part["normalized_material"] == "ABS", (
        "arbitration's answer was replaced by the pricing material. A lower-ranked source "
        "does not win the datum by being convenient -- the reports must still show ABS.")


def test_the_substitution_is_recorded_on_the_part():
    """Never silently. The conflict has to survive to the checks and the reports, or a
    number appears on the sheet with nothing behind it."""
    from estimator import estimate_material
    part = _real_door()
    estimate_material(part)
    conflict = part.get("material_priced_as")
    assert conflict and conflict["priced_material"] == "POLYCARBONATE"
    assert conflict["arbitrated_material"] == "ABS"
    assert any(f.get("flag") == "material_unpriceable_substituted"
               for f in part.get("review_flags") or [])


def test_the_door_is_priced_at_the_polycarbonate_rate():
    """The whole point, in money: a 1202 x 689 x 6mm door at GBP 21.70/m2 plus 4% scrap."""
    from estimator import estimate_material
    me = estimate_material(_real_door())
    assert me["material"] == "POLYCARBONATE"
    assert me["unit_material_cost_gbp"] == pytest.approx(18.69, abs=0.01), (
        "the door costed GBP 0.00 before this rule; if the figure moves, the rate table or "
        "the blank changed and the estimate moved with it")


def test_a_priceable_winner_is_never_second_guessed():
    """A rate that exists is used, whatever else was read. This is a rescue, not a preference
    for the cheapest reading on the part."""
    part = {"normalized_material": "MILD STEEL", "materials": ["ACRYLIC"]}
    assert price_from(part, "MILD STEEL") == ("MILD STEEL", None)


def test_nothing_happens_when_no_reading_has_a_rate():
    assert price_from({"materials": ["ABS", "ABS"]}, "ABS") == ("ABS", None)


def test_the_displaced_record_is_preferred_over_raw_tokens():
    """What arbitration displaced is a structured reading with a named source; the raw token
    list is looser. Better evidence first."""
    part = {"normalized_material": "ABS", "materials": ["ACRYLIC"],
            "_displaced": {"normalized_material": [
                {"value": "POLYCARBONATE", "source": "drawing_deterministic"}]}}
    material, conflict = price_from(part, "ABS")
    assert material == "POLYCARBONATE"
    assert conflict["priced_material_source"] == "drawing_deterministic"


# ── and it is never silent ──────────────────────────────────────────────────────────
def _job(*parts):
    return {"estimate_summary": {"part_estimates": list(parts)}}


def test_a_rescued_part_is_reported_as_an_unconfirmed_material():
    part = _door()
    part["material_priced_as"] = {"arbitrated_material": "ABS",
                                  "priced_material": "POLYCARBONATE",
                                  "priced_material_source": "drawing text"}
    found = inv.check_a_material_we_cannot_price_is_declared(_job(part))
    assert [v["severity"] for v in found] == [WARNING]
    msg = found[0]["message"]
    assert "MATERIAL IS UNCONFIRMED" in msg and "ABS" in msg and "POLYCARBONATE" in msg


def test_an_unrescued_part_blocks_and_says_it_is_ours():
    """No estimator input creates a rate the engine does not have. Calling this the
    estimator's job would put an unworkable line on their checklist."""
    found = inv.check_a_material_we_cannot_price_is_declared(
        _job({"part_number": "X", "normalized_material": "ABS"}))
    assert [v["severity"] for v in found] == [BLOCKING]
    msg = found[0]["message"]
    assert "No estimator input fixes this" in msg
    assert "UNDER-CHARGED" in msg, "say which direction the money went"


def test_a_priceable_job_raises_nothing():
    assert inv.check_a_material_we_cannot_price_is_declared(
        _job({"part_number": "Y", "normalized_material": "MILD STEEL"})) == []


def test_a_part_with_no_material_is_left_to_another_check():
    """Absence of a material is a different defect with a different owner. Reporting it here
    too would put one fault on two checklists."""
    assert inv.check_a_material_we_cannot_price_is_declared(
        _job({"part_number": "Z", "normalized_material": ""})) == []


def test_an_unreadable_summary_is_unverified_not_a_pass():
    out = inv.check_a_material_we_cannot_price_is_declared(None)
    assert out and out[0]["severity"] == UNVERIFIED


def test_the_check_runs_on_every_job():
    assert inv.check_a_material_we_cannot_price_is_declared in inv.CHECKS
