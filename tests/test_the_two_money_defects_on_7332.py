"""The two 7332 defects that move money: where a section length came from, and a fabricated
part published as bought-in.

1. Section stock is priced PER METRE, so the length is the money. _infer_section_length_mm
   tries four real sources and then falls back to "the largest dimension on the part" — and
   until this build nothing downstream could tell that fallback from a cut-list reading,
   because it returned a bare float either way.

   THE POLICY, as James set it after an earlier cut of this guard refused every fallback:
     - stamp the rung AND the reader on the line (7332-01-002's 1,397 mm is section_stock
       read by llm_full_extract — a reading, priced like one);
     - a fallback is still PRICED, INDICATIVE, with a flag naming the figure — a stand's
       height is usually a fair figure for its leg, and 1.4 m on a 453 mm base is not absurd;
     - it is refused only when the figure cannot be a length of stock: a cut-path total off
       the same record (the 9,106 mm page sum), or longer than any bar of section.

2. bought_in_policy already states the rule — "a part with its own measured flat is a
   fabricated leaf whatever a transcribed hierarchy says" — but it was only used to RAISE a
   conflict, never to decide the kind. So 7332-01-001 BASE, nested as 5 mm steel and charged
   £3.03 of laser, was published as "bought_in" on the Canonical BOM and provenance tab.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import blank_credibility as bc  # noqa: E402
import estimator as e  # noqa: E402
import invariants as inv  # noqa: E402
import route_compiler as rc  # noqa: E402


# ── 1. the length, and where it came from ────────────────────────────────────
def _leg(**over):
    part = {"part_number": "7332-01-002", "description": "LEG",
            "normalized_material": "MILD STEEL", "quantity": 2,
            "section_stock": {"a": 15.88, "b": 15.88, "t": 1.2}}
    part.update(over)
    return part


def _flags(part):
    return [str(f) for f in (part.get("review_flags") or [])]


def test_the_length_search_records_the_rung_and_the_reader():
    read = _leg(section_stock={"a": 15.88, "b": 15.88, "t": 1.2, "length_mm": 420.0,
                               "source": "llm_full_extract"})
    assert e._infer_section_length_mm(read) == 420.0
    assert read["_section_length_source"] == "section_stock"
    assert read["_section_length_reader"] == "llm_full_extract"

    cut_list = _leg(section_stock={"a": 30, "b": 30, "t": 1.5, "length_mm": 1125.0,
                                   "detection_path": "weldment_cut_list"})
    e._infer_section_length_mm(cut_list)
    assert cut_list["_section_length_reader"] == "weldment_cut_list"

    fallback = _leg(all_dimensions_mm=[1400.0, 15.88, 297.0])
    assert e._infer_section_length_mm(fallback) == 1400.0
    assert fallback["_section_length_source"] == e.SECTION_LENGTH_FALLBACK == "max_dimension_fallback"
    assert fallback["_section_length_reader"] == "all_dimensions_mm"


def test_the_7332_leg_as_transcribed_is_a_reading_not_a_fallback():
    """THE CORRECTION. The real job JSON carries section_stock.length_mm 1397.0 from
    llm_full_extract, alongside a 9,106 mm page-summed cut path. The reading wins, the leg
    is priced, and nothing on the line says 'not stated' — whatever the cut path says."""
    leg = _leg(section_stock={"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1397.0, "source": "llm_full_extract"},
               all_dimensions_mm=[9106.0, 1397.0, 12.7],
               geometry_rollup={"estimated_cut_length_mm": 9106.0})
    pe = e.estimate_part(leg, job_quantity=6)
    me = pe["material_estimate"]
    assert me["unit_material_cost_gbp"] > 0
    assert me["stock_estimate"]["section_length_mm"] == 1397.0
    assert me["stock_estimate"]["section_length_source"] == "section_stock"
    assert me["stock_estimate"]["section_length_reader"] == "llm_full_extract"
    assert me["stock_estimate"]["section_length_indicative"] is False
    assert not any("not stated" in f.lower() for f in _flags(leg))


def test_a_fallback_length_is_priced_indicative_and_flagged():
    """1.4 m on an A3 stand is not absurd: it is priced, and the line says what it is."""
    leg = _leg(all_dimensions_mm=[1400.0, 15.88, 297.0])
    pe = e.estimate_part(leg, job_quantity=6)
    me = pe["material_estimate"]
    assert me["unit_material_cost_gbp"] > 0, "a fallback is priced, not withheld"
    assert me["stock_estimate"]["section_length_source"] == e.SECTION_LENGTH_FALLBACK
    assert me["stock_estimate"]["section_length_indicative"] is True
    flag = [f for f in _flags(leg) if "length not stated" in f.lower()]
    assert flag, "the line must say the length was not stated"
    assert "1,400" in flag[0] and "INDICATIVE" in flag[0]
    assert not leg.get("_consumable_qty_unknown")


def test_a_fallback_that_is_the_cut_path_is_refused():
    """The one case that IS absurd: the biggest number on the record is the page reader's
    summed cut path. Nine metres of tube priced off a total of cutting is not a length."""
    leg = _leg(all_dimensions_mm=[9106.0, 15.88, 297.0],
               geometry_rollup={"estimated_cut_length_mm": 9106.0})
    pe = e.estimate_part(leg, job_quantity=6)
    assert (pe.get("material_estimate") or {}).get("unit_material_cost_gbp") is None
    flag = [f for f in _flags(leg) if "NOT STATED" in f]
    assert flag and "cut path" in flag[0]
    assert leg.get("_consumable_qty_unknown") is True


def test_a_fallback_longer_than_a_bar_of_stock_is_refused():
    leg = _leg(all_dimensions_mm=[8000.0, 15.88])
    pe = e.estimate_part(leg, job_quantity=6)
    assert (pe.get("material_estimate") or {}).get("unit_material_cost_gbp") is None
    assert any("longer than any bar" in f for f in _flags(leg))


def test_a_stated_cut_length_still_prices_exactly_as_before():
    part = _leg(section_stock={"a": 15.88, "b": 15.88, "t": 1.2, "length_mm": 420.0})
    pe = e.estimate_part(part, job_quantity=6)
    assert (pe.get("material_estimate") or {}).get("unit_material_cost_gbp") > 0
    assert not any("not stated" in f.lower() for f in _flags(part))


def test_the_absurdity_test_is_one_function():
    """The estimator, the invariant and the pre-flight must agree what 'not a length' is."""
    p = {"geometry_rollup": {"estimated_cut_length_mm": 9106.0}}
    assert bc.section_length_matches_a_cut_path(p, 9106.0) == "geometry_rollup.estimated_cut_length_mm (9,106 mm)"
    assert bc.section_length_matches_a_cut_path(p, 9200.0) == "geometry_rollup.estimated_cut_length_mm (9,106 mm)"
    assert bc.section_length_matches_a_cut_path(p, 1397.0) is None
    assert bc.section_length_is_absurd(p, 1397.0) is None
    assert "cut path" in bc.section_length_is_absurd(p, 9106.0)
    assert "bar of section" in bc.section_length_is_absurd({}, 8000.0)
    # the envelope test only fires when a caller has an envelope to test against
    assert bc.section_length_is_absurd({}, 1400.0, envelope_mm=453.0) is not None
    assert bc.section_length_is_absurd({}, 1400.0, envelope_mm=1400.0) is None
    assert bc.section_length_is_absurd({}, 1400.0, envelope_mm=None) is None


def test_the_job_envelope_is_read_from_what_the_pack_states():
    assert bc.stated_job_envelope_mm({}) is None
    assert bc.stated_job_envelope_mm({"llm_full_extract": {"parts": [
        {"part_number": "7332-01", "overall_size_mm": "453 x 297 x 1400"},
        {"part_number": "7332-01-001", "overall_size_mm": [453, 297]},
    ]}}) == 1400.0


# ── the invariant over the priced record ─────────────────────────────────────
def _job(part, **extra):
    return {"parts": [part], "estimate_summary": {"part_estimates": [part]}, **extra}


def _priced_section(length_mm, source, *, flags=(), **over):
    p = {"part_number": "7332-01-002", "stock_form": "tube", "review_flags": list(flags),
         "material_estimate": {"unit_material_cost_gbp": 5.86, "stock_form": "tube",
                               "stock_estimate": {"section_length_mm": length_mm,
                                                  "section_length_source": source,
                                                  "section_length_reader": "all_dimensions_mm"}}}
    p.update(over)
    return p


def _codes(summary):
    return {(v["code"], v["severity"])
            for v in inv.check_a_section_length_is_a_reading_or_says_it_is_not(summary)}


def test_a_reading_raises_nothing():
    p = _priced_section(1397.0, "section_stock")
    assert _codes(_job(p)) == set()


def test_a_flagged_fallback_is_a_warning_not_a_block():
    p = _priced_section(1400.0, e.SECTION_LENGTH_FALLBACK,
                        flags=["section length not stated — taken as largest dimension 1,400mm (INDICATIVE)"])
    assert _codes(_job(p)) == {("section_length_fallback_indicative", inv.WARNING)}


def test_a_silent_fallback_blocks():
    p = _priced_section(1400.0, e.SECTION_LENGTH_FALLBACK)
    assert _codes(_job(p)) == {("section_length_fallback_unflagged", inv.BLOCKING)}


def test_a_fallback_priced_from_the_cut_path_blocks():
    p = _priced_section(9106.0, e.SECTION_LENGTH_FALLBACK,
                        flags=["section length not stated (INDICATIVE)"],
                        geometry_rollup={"estimated_cut_length_mm": 9106.0})
    assert _codes(_job(p)) == {("section_priced_from_a_cut_path", inv.BLOCKING)}


def test_a_fallback_far_beyond_the_stated_envelope_is_named_but_still_a_warning():
    p = _priced_section(1400.0, e.SECTION_LENGTH_FALLBACK,
                        flags=["section length not stated (INDICATIVE)"])
    out = inv.check_a_section_length_is_a_reading_or_says_it_is_not(
        _job(p, llm_full_extract={"parts": [{"part_number": "7332-01", "overall_size_mm": "453 x 297"}]}))
    assert [(v["code"], v["severity"]) for v in out] == [("section_length_fallback_indicative", inv.WARNING)]
    assert "3.1x" in out[0]["message"]


def test_a_reading_that_equals_the_cut_path_is_named():
    p = _priced_section(9106.0, "section_stock", geometry_rollup={"estimated_cut_length_mm": 9106.0})
    assert _codes(_job(p)) == {("section_reading_equals_the_cut_path", inv.WARNING)}


def test_the_invariant_is_registered():
    assert inv.check_a_section_length_is_a_reading_or_says_it_is_not in inv.CHECKS


# ── the pre-flight ───────────────────────────────────────────────────────────
def _write_job(tmp_path, parts):
    path = tmp_path / "7332-01.json"
    path.write_text(json.dumps({"parts": parts, "assumed_job_quantity": 6,
                                "llm_full_extract": {"parts": [], "routes": []}}),
                    encoding="utf-8")
    return str(path)


def test_the_preflight_passes_a_transcribed_leg(tmp_path, capsys):
    import preflight_tube_bend as pf
    leg = _leg(section_stock={"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1397.0, "source": "llm_full_extract"},
               geometry_rollup={"estimated_cut_length_mm": 9106.0})
    assert pf.main([_write_job(tmp_path, [leg])]) == 0
    out = capsys.readouterr().out
    assert "source section_stock" in out and "read by llm_full_extract" in out
    assert "PASS" in out


def test_the_preflight_refuses_the_llm_extract_sidecar(tmp_path):
    """On 7332 the newest .json under output/ was 7332-01_llm_extract.json — the whole-
    document extract written beside the workbook, whose rows carry tube_section, not
    section_stock — and the pre-flight said 'no tube parts on this job' about a file that
    was never the job. Named explicitly it is refused; found by glob it is skipped."""
    import preflight_tube_bend as pf
    extract = {"source": "llm_full_extract", "found": True,
               "parts": [{"part_number": "7332-01-002", "tube_section": "15.875x15.875x1.2",
                          "cut_length_mm": 1397.0}]}
    side = tmp_path / "7332-01_llm_extract.json"
    side.write_text(json.dumps(extract), encoding="utf-8")
    assert pf._looks_like_a_job(extract) is False
    assert pf._looks_like_a_job({"parts": [{"part_number": "7332-01-002"}]}) is True
    import pytest
    with pytest.raises(SystemExit) as exc:
        pf.main([str(side)])
    assert "not a job document" in str(exc.value)


def test_the_preflight_fails_a_tube_priced_from_the_cut_path(tmp_path, capsys, monkeypatch):
    """Belt and braces: if the estimator's own guard ever lets a cut-path figure through as
    a priced fallback length, the pre-flight catches it before the run, not after."""
    import preflight_tube_bend as pf

    def _leaky_estimate(part, job_quantity=None):
        part["stock_form"] = "tube"
        return {"material_estimate": {"unit_material_cost_gbp": 38.0, "stock_form": "tube",
                                      "stock_estimate": {"section_length_mm": 9106.0,
                                                         "section_length_source": e.SECTION_LENGTH_FALLBACK,
                                                         "section_length_reader": "all_dimensions_mm"}}}
    monkeypatch.setattr(e, "estimate_part", _leaky_estimate)
    leg = _leg(all_dimensions_mm=[9106.0, 15.88], geometry_rollup={"estimated_cut_length_mm": 9106.0})
    assert pf.main([_write_job(tmp_path, [leg])]) == 1
    assert "NOT A LENGTH" in capsys.readouterr().out


# ── 2. measured geometry of its own outranks a transcribed role ──────────────
def test_a_part_with_its_own_measured_flat_is_not_published_as_bought_in():
    base = {"part_number": "7332-01-001", "description": "BASE",
            "normalized_material": "MILD STEEL",
            "page_roles": ["bought_in"],              # the transcribed role
            "blank_length_mm": 453.0, "blank_width_mm": 300.0,
            "flat_pattern_detected": True,
            "dxf_source_file": "7332-01-001_5mm MS_revK.DXF"}
    assert rc._bought_in_record(base) is False
    assert {n.part_number: n.kind for n in rc.build_part_graph([base], {})["nodes"]} == {
        "7332-01-001": "leaf"}


def test_a_genuine_bought_in_is_untouched():
    """Narrowness is the point — a castor has a role and no measured flat, and stays bought-in."""
    castor = {"part_number": "BI-CASTOR", "description": "CASTOR", "page_roles": ["bought_in"]}
    assert rc._bought_in_record(castor) is True
    assert {n.part_number: n.kind for n in rc.build_part_graph([castor], {})["nodes"]} == {
        "BI-CASTOR": "bought_in"}
