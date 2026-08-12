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


# ── the engine must not be the reason a number does not exist ───────────────────────
# config carries no rate for ABS, PETG, PVC, FOAMEX, PP or PS, and its comment says why:
# "a price is a commercial fact and SDI owns it; inventing one would put a number on a quote
# that nobody has agreed to." That is right. But declining to INVENT a rate is not the same
# as declining to LOOK ONE UP, and treating them as the same thing is what left the door at
# GBP 0.00 with nobody told why. The same web/LLM lookup the bought-in fallback already uses
# can be asked about a SHEET -- and what it returns is an AI estimate, so it goes in front of
# an estimator and never into a total.
def test_the_indication_never_reaches_a_total(monkeypatch):
    from estimator import estimate_material
    import estimator as _est
    monkeypatch.setattr(_est, "market_indication_for",
                        lambda part, material: {"gbp_per_sheet": 180.0, "gbp_per_m2": 28.8,
                                                "sheet_mm": [3050, 2050], "thickness_mm": 6,
                                                "confidence": 0.5, "source": "llm_market_estimate"})
    part = _real_door()
    me = estimate_material(part)
    assert part["material_market_indication"]["gbp_per_m2"] == 28.8
    assert me["unit_material_cost_gbp"] == pytest.approx(18.69, abs=0.01), (
        "the AI indication changed the priced figure. It is not reproducible and must never "
        "be the difference between winning and losing a job -- it is shown, not summed.")


def test_the_indication_is_asked_for_even_when_a_substitution_rescued_the_price(monkeypatch):
    """It is how an estimator judges whether the substitution matters. If ABS and
    POLYCARBONATE come back at similar money the conflict is commercially small and the
    ruling is easy; if they are far apart, it is the whole question."""
    import estimator as _est
    asked = []
    monkeypatch.setattr(_est, "market_indication_for",
                        lambda part, material: asked.append(material) or None)
    _est.estimate_material(_real_door())
    assert asked == ["ABS"], "asked about the wrong material, or not asked at all"


def test_a_priceable_material_is_never_looked_up(monkeypatch):
    """One network call per unpriceable material is the budget. Asking about MILD STEEL,
    which config prices, spends money and time for an answer we already hold."""
    import estimator as _est
    asked = []
    monkeypatch.setattr(_est, "market_indication_for",
                        lambda part, material: asked.append(material) or None)
    _est.estimate_material({"part_number": "S", "normalized_material": "MILD STEEL",
                            "quantity": 1, "normalized_thickness_mm": 2,
                            "normalized_geometry": {"blank_length_mm": 300,
                                                    "blank_width_mm": 200}})
    assert asked == []


def test_offline_asks_nothing(monkeypatch):
    """SDI_OFFLINE means offline. The rules suite must never dial a provider.

    ASSERTED BY COUNTING CALLS, NOT BY THE RETURN VALUE. Deleting this guard left the test
    passing, because lookup_web_ai_price has its own offline check and returns found=False --
    so the outer guard could vanish and nothing would notice until the day the inner one
    moved. Defence in depth is only depth if each layer is tested for itself.
    """
    import estimator as _est, web_ai_price_lookup as _w
    _est._MARKET_INDICATION_CACHE.clear()
    calls = []
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: calls.append(a) or {"gbp_per_m2": 1.0})
    monkeypatch.setenv("SDI_OFFLINE", "1")
    assert _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS") is None
    assert calls == [], "the offline guard did not short-circuit; a provider was dialled"
    _est._MARKET_INDICATION_CACHE.clear()


def test_the_indication_is_written_but_never_read_by_anything_that_costs():
    """The guarantee stated structurally, because the behavioural version could not fail: a
    mutant that assigned the indication onto the part still left the priced figure alone,
    since the cost is built from locals. So assert the shape instead -- the key is WRITTEN by
    the estimator and READ only where things are reported, never where money is computed.
    """
    import ast
    KEY = "material_market_indication"
    writers, readers = set(), set()
    for path in sorted((ROOT / "src").glob("*.py")):
        if not path.is_file() or path.name.startswith("_") or ".baclkup" in path.name:
            continue
        try:
            body = ast.unparse(ast.parse(path.read_text(encoding="utf-8-sig", errors="replace")))
        except SyntaxError:
            continue
        if KEY not in body:
            continue
        (writers if f"['{KEY}'] =" in body else readers).add(path.name)
    assert writers == {"estimator.py"}, f"unexpected writer(s) of {KEY}: {writers}"
    costing = {"wb_populate.py", "pricing_service.py", "bay_rollup.py", "bought_in_pricing.py"}
    assert not (readers & costing), (
        f"{KEY} is read by a module that computes money: {readers & costing}. It is an AI "
        f"estimate -- not reproducible, not firm -- and must never be summed.")


def test_the_lookup_is_cached_per_material_and_gauge(monkeypatch):
    """A job with six ABS panels asked six times for one answer -- six round trips, and six
    chances to return six different numbers for the same material."""
    import estimator as _est, web_ai_price_lookup as _w
    _est._MARKET_INDICATION_CACHE.clear()
    calls = []
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path", lambda key: None)   # disk tested below
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: calls.append(a) or {"gbp_per_sheet": 180.0,
                                                            "gbp_per_m2": 28.8})
    for _ in range(6):
        _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS")
    assert len(calls) == 1, f"asked {len(calls)} times for one material and gauge"
    _est._MARKET_INDICATION_CACHE.clear()


def test_the_rate_survives_between_runs(monkeypatch, tmp_path):
    """A SHEET RATE IS NOT A PER-RUN FACT. In-process memoisation fixes one run; the next run
    pays again and can disagree with the last one about what a job's material costs. Two runs
    of the same pack must not return two different material totals because a model answered
    differently on a Tuesday."""
    import estimator as _est, web_ai_price_lookup as _w
    calls = []
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path",
                        lambda key: tmp_path / f"{key[0]}_{key[1]}.json")
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: calls.append(a) or {"gbp_per_sheet": 180.0,
                                                            "gbp_per_m2": 28.8})
    _est._MARKET_INDICATION_CACHE.clear()
    first = _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS")
    _est._MARKET_INDICATION_CACHE.clear()          # a fresh process
    second = _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS")
    assert len(calls) == 1, "the second run paid for an answer the first run already had"
    assert second["gbp_per_m2"] == first["gbp_per_m2"]
    _est._MARKET_INDICATION_CACHE.clear()


def test_a_failed_lookup_is_not_written_down(monkeypatch, tmp_path):
    """A miss is usually a network or credit problem, not a fact about the material. Caching
    it would make one bad afternoon permanent -- and SerpAPI being out of credit today would
    silently price ABS at nothing for every future job."""
    import estimator as _est, web_ai_price_lookup as _w
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path", lambda key: tmp_path / "abs.json")
    monkeypatch.setattr(_w, "market_sheet_rate_indication", lambda *a, **k: None)
    _est._MARKET_INDICATION_CACHE.clear()
    assert _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS") is None
    assert not (tmp_path / "abs.json").exists(), "a failed lookup was cached to disk"
    _est._MARKET_INDICATION_CACHE.clear()


# ── it prices the line, and the job can never go out firm on it ─────────────────────
# THE UNDER-CHARGE IS WORSE THAN A MARKED PROVISIONAL FIGURE. Leaving material at GBP 0.00
# because no rate exists means the job is short by an invisible amount. Pricing it from a
# market lookup means the job is complete and one line is explicitly a model's reading rather
# than a supplier's commitment -- which the firm/provisional gate already knows how to carry.
def _llm_door(monkeypatch, rate_m2=26.87, sheet=168.0):
    import estimator as _est, web_ai_price_lookup as _w
    _est._MARKET_INDICATION_CACHE.clear()
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path", lambda key: None)
    monkeypatch.setattr(_w, "market_sheet_rate_indication", lambda *a, **k: {
        "gbp_per_sheet": sheet, "gbp_per_m2": rate_m2, "sheet_mm": [3050, 2050],
        "thickness_mm": 6, "confidence": 0.5, "source": "llm_market_estimate"})
    part = {"part_number": "11650-01-05A", "normalized_material": "ABS", "materials": [],
            "quantity": 1, "normalized_thickness_mm": 6,
            "normalized_geometry": {"blank_length_mm": 1202, "blank_width_mm": 689}}
    return part, _est.estimate_material(part)


def test_an_unpriceable_material_is_costed_from_the_market_rate(monkeypatch):
    part, me = _llm_door(monkeypatch)
    assert me["cost_method"] == "llm_market_sheet_rate"
    # 0.8282 m2 x GBP 26.87/m2 x 1.04 scrap
    assert me["unit_material_cost_gbp"] == pytest.approx(23.14, abs=0.05)
    assert me["unit_material_cost_gbp"] > 0, "the silent GBP 0.00 under-charge is back"


def test_the_arbitrated_material_still_survives_it(monkeypatch):
    part, _ = _llm_door(monkeypatch)
    assert part["normalized_material"] == "ABS"


def test_the_line_is_stamped_as_a_model_estimate_not_a_catalogue_hit(monkeypatch):
    import price_provenance as _pp
    _, me = _llm_door(monkeypatch)
    stamp = me["price_source"]
    assert _pp.stamp_source_class(stamp) == "ai_estimate", (
        "an LLM sheet rate must not read as a catalogue price; every reader downstream "
        "decides what it may be used for from this one word")
    assert _pp.stamp_affects_total(stamp) is True, "it IS in the total, and must say so"
    assert _pp.price_firmness(stamp)["firm"] is False


def test_a_real_rate_is_never_displaced_by_a_market_lookup(monkeypatch):
    """The lookup fires only where config holds nothing. A material we can price is priced
    from what we hold, whatever a model would have said about it."""
    import estimator as _est, web_ai_price_lookup as _w
    _est._MARKET_INDICATION_CACHE.clear()
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: {"gbp_per_m2": 999.0, "gbp_per_sheet": 6245.0,
                                         "source": "llm_market_estimate"})
    me = _est.estimate_material({"part_number": "P", "normalized_material": "POLYCARBONATE",
                                 "quantity": 1, "normalized_thickness_mm": 6,
                                 "normalized_geometry": {"blank_length_mm": 1202,
                                                         "blank_width_mm": 689}})
    assert me["cost_method"] == "acrylic_area_per_m2_provisional"
    assert me["unit_material_cost_gbp"] == pytest.approx(18.69, abs=0.05)
    _est._MARKET_INDICATION_CACHE.clear()


def test_the_console_line_does_not_claim_it_is_unused(monkeypatch, capsys):
    """It said "NOT USED IN THE TOTAL" for a figure that is now in the total. A sentence that
    was true when written and false after the next change is how a reader stops trusting the
    console -- and this one was three edits old."""
    _llm_door(monkeypatch)
    said = capsys.readouterr().out
    assert "NOT USED IN THE TOTAL" not in said
    assert "PRICED FROM IT" in said and "cannot go out firm" in said


def test_an_internally_priced_line_is_not_classified_as_unpriced():
    """THE THIRD TIME TODAY one field was asked a question it does not answer. `selected` is
    filled only by an EXTERNAL lookup, so every internally computed price -- the acrylic
    rate, the workbook sheet-steel formula, config's GBP/kg -- classified as "unpriced" with
    its money in the total, and price_firmness explained a real figure as "a unpriced price
    carries no commitment"."""
    import estimator as _est, price_provenance as _pp
    for name in ("acrylic_area_per_m2_provisional", "config_default_material_rates",
                 "workbook_sheet_steel_formula"):
        stamp = _est._build_price_source_metadata({}, fallback_source=name, applied=True)
        assert _pp.stamp_source_class(stamp) != "unpriced", name
    # and a price that genuinely was not applied keeps its honest answer
    assert _est._build_price_source_metadata(
        {}, fallback_source="system_cost_not_found", applied=False)["source_class"] == "unpriced"


def test_a_partial_lookup_result_cannot_take_the_run_down(monkeypatch, capsys):
    """The message is the least important thing in that function and was the only thing that
    could raise: a hard subscript on a key the lookup is not obliged to return. A model that
    answers with a price and no source name must not kill an estimate."""
    import estimator as _est, web_ai_price_lookup as _w
    _est._MARKET_INDICATION_CACHE.clear()
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path", lambda key: None)
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: {"gbp_per_m2": 26.87})     # no source, no sheet price
    me = _est.estimate_material({"part_number": "D", "normalized_material": "ABS",
                                 "quantity": 1, "normalized_thickness_mm": 6,
                                 "normalized_geometry": {"blank_length_mm": 1202,
                                                         "blank_width_mm": 689}})
    assert me["unit_material_cost_gbp"] > 0
    assert "market indication" in capsys.readouterr().out
    _est._MARKET_INDICATION_CACHE.clear()


def test_the_suite_never_writes_into_the_repository_cache():
    """A test wrote a real ABS rate into cache/market_sheet_rates and three unrelated tests
    then failed against it. A cache that survives between runs is the point of the feature and
    a hazard in a suite: every test that reaches this path must supply its own location."""
    live = ROOT / "cache" / "market_sheet_rates"
    assert not live.exists() or not any(live.iterdir()), (
        f"{live} holds cached rates written during a test run. Patch _market_cache_path in "
        f"any test that can reach market_indication_for.")


def test_an_llm_priced_line_is_reported_as_not_a_supplier_price():
    """The line carries money, so the under-charge is closed -- and nobody has agreed to it.
    That has to reach an estimator as its own finding, not be inferred from a source string
    in a provenance tab."""
    part = {"part_number": "11650-01-05A",
            "material_market_indication": {"material": "ABS", "gbp_per_m2": 26.87,
                                           "source": "llm_market_estimate"},
            "material_estimate": {"cost_method": "llm_market_sheet_rate"}}
    found = inv.check_a_material_we_cannot_price_is_declared(_job(part))
    assert [v["severity"] for v in found] == [WARNING], \
        "an LLM-priced material raises nothing; the figure looks like any other price"
    msg = found[0]["message"]
    assert "NOBODY HAS AGREED TO THIS PRICE" in msg
    assert "cannot be released as firm" in msg
    assert "26.87" in msg and "ABS" in msg


def test_an_llm_priced_line_is_no_longer_reported_as_having_no_rate():
    """Two findings for one line is how a checklist stops being worked. Once it is priced it
    is not the blocking 'this material costs nothing' case any more."""
    part = {"part_number": "X", "normalized_material": "ABS",
            "material_market_indication": {"material": "ABS", "gbp_per_m2": 26.87,
                                           "source": "llm"},
            "material_estimate": {"cost_method": "llm_market_sheet_rate"}}
    codes = [v.get("code") or v.get("name") or v["message"][:40]
             for v in inv.check_a_material_we_cannot_price_is_declared(_job(part))]
    assert len(codes) == 1, f"the same line raised {len(codes)} findings: {codes}"


def test_a_miss_written_as_an_empty_record_is_still_not_a_cached_answer(monkeypatch, tmp_path):
    """The first version of this mutant was self-masking -- dict(None) raises and the write
    fails anyway. This is the version that would really happen: a tidy-minded change writing
    `found or {}` and turning one failed afternoon into a permanent zero for that material."""
    import estimator as _est, web_ai_price_lookup as _w
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(_est, "_market_cache_path", lambda key: tmp_path / "abs.json")
    monkeypatch.setattr(_w, "market_sheet_rate_indication", lambda *a, **k: None)
    _est._MARKET_INDICATION_CACHE.clear()
    _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS")
    assert not (tmp_path / "abs.json").exists()
    # and the next run must be free to ask again rather than inherit the failure
    _est._MARKET_INDICATION_CACHE.clear()
    calls = []
    monkeypatch.setattr(_w, "market_sheet_rate_indication",
                        lambda *a, **k: calls.append(a) or {"gbp_per_m2": 26.87})
    assert _est.market_indication_for({"normalized_thickness_mm": 6}, "ABS")["gbp_per_m2"] == 26.87
    assert calls, "a failed lookup was remembered and the material stayed unpriced forever"
    _est._MARKET_INDICATION_CACHE.clear()


# ── the check must not cry wolf on lines that carry money ───────────────────────────
# INTRODUCED AND CAUGHT IN ONE DAY. The first version read normalized_material alone and
# assumed that field always holds a material. On 11650's bought-in fixings it holds the
# pointer text "SEE INDIVIDUAL DRAWINGS", which no rate table knows -- so four fixings priced
# at GBP 0.10, GBP 0.08 and GBP 0.02 ON THE SAME SHEET were reported as BLOCKING
# under-charges, taking the job from 11 blockers to 12 for no reason. A check that cries wolf
# on priced lines gets ignored on the day it is right.
@pytest.mark.parametrize("part,expected,why", [
    ({"part_number": "FIXING1399", "normalized_material": "SEE INDIVIDUAL DRAWINGS",
      "material_estimate": {"unit_material_cost_gbp": 0.02}}, [],
     "a priced bought-in is not an under-charge, whatever its material string says"),
    ({"part_number": "X", "normalized_material": "SEE INDIVIDUAL DRAWINGS"}, [],
     "a pointer names no substance; demanding a rate for it asks the impossible"),
    ({"part_number": "Z", "normalized_material": "ABS",
      "material_estimate": {"unit_material_cost_gbp": 23.14}}, [],
     "ABS priced from the market lookup is costed, so nothing is missing"),
    ({"part_number": "Y", "normalized_material": "ABS"}, [inv.BLOCKING],
     "the real case must survive the fix: a real material, no rate, no cost"),
    ({"part_number": "W", "normalized_material": "ABS",
      "material_estimate": {"unit_material_cost_gbp": 0}}, [inv.BLOCKING],
     "a recorded ZERO is exactly the under-charge this check exists to find"),
])
def test_only_a_line_that_really_costs_nothing_is_reported(part, expected, why):
    found = inv.check_a_material_we_cannot_price_is_declared(_job(part))
    assert [v["severity"] for v in found] == expected, why
