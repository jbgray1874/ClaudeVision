"""A sighted construction is kept and costed (D-489 to D-492).

The K-Wellness 16:53 book, reviewed: the AI read returned a usable provisional construction,
and the engine lost or under-used parts of it —

  - the rear graphic panel and base holders, read as made mild-steel parts with sizes and a
    route, lost the route to the word GRAPHIC in their names (D-489);
  - no fold count was asked for, so a folded part's run time was 0 and the workbook printed
    per-part fold rates of pieces over set-up alone (36,036/hr), and finished face sizes were
    priced as flat blanks with no flanges (D-490);
  - "per unit" labels were one line of one label, with no application time (D-491);
  - a re-read asked because the question changed could replace the whole construction, and
    nothing said what moved (D-492).

Nothing here names a job, a customer or a part code.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402

SRC = ROOT / "src"


def _sighted(name, kind="fabricated", blank=(1500, 500, 2),
             ops=("laser_cutting", "folding", "powder_coating"), **extra):
    p = {"name": name, "kind": kind, "quantity": 1, "material_guess": "MILD STEEL",
         "sighted_material": "sheet steel",
         "assumed_blank_mm": {"length": blank[0], "width": blank[1], "thickness": blank[2]},
         "operations": list(ops)}
    p.update(extra)
    return p


def _parts(*sighted):
    return cs.parts_from_concept({"product": {"name": "UNIT"}, "parts": list(sighted)}, "JOB")


def _labour_ops(part):
    import estimator as E
    pe = E.estimate_part(part, job_quantity=200)
    return sorted((pe.get("labour_estimate") or {}).get("costs_gbp", {})), pe


# ── D-489: an evidenced made part keeps its route whatever its name ──────────────────────

def test_the_name_alone_no_longer_decides_make_or_buy():
    named, plain = _parts(_sighted("Rear graphic panel"), _sighted("Rear panel"))
    ops_named, _ = _labour_ops(named)
    ops_plain, _ = _labour_ops(plain)
    assert ops_named == ops_plain
    assert {"laser_cutting", "folding", "powder_coating"} <= set(ops_named)
    assert not named.get("special_finish_item")
    assert "bought_in" not in (named.get("page_roles") or [])


def test_without_the_evidence_the_name_still_rules():
    graphic, unsized = _parts(_sighted("Graphic header", kind="graphic"),
                              _sighted("Graphic panel", blank=(0, 0, 2)))
    assert _labour_ops(graphic)[0] == ["handling"]
    assert _labour_ops(unsized)[0] == ["handling"]


def test_the_evidenced_make_test_needs_all_three():
    import bought_in_policy as bp
    (made,) = _parts(_sighted("Rear graphic panel"))
    assert bp.read_states_a_made_part(made)
    assert not bp.read_states_a_made_part(dict(made, concept_kind="bought_in"))
    assert not bp.read_states_a_made_part(dict(made, normalized_material="PRINTED_PAPER"))
    assert not bp.read_states_a_made_part(dict(made, blank_width_mm=0))
    assert not bp.read_states_a_made_part(dict(made, inferred_operations=["handling"]))
    assert not bp.read_states_a_made_part(dict(made, _estimator_make_or_buy="buy"))


def test_pricing_and_costing_ask_the_same_question():
    src = (SRC / "pricing_service.py").read_text(encoding="utf-8")
    assert "read_states_a_made_part as _read_made" in src
    est = (SRC / "estimator.py").read_text(encoding="utf-8")
    assert "read_states_a_made_part as _read_made" in est


# ── D-490: folds, flanges and cut-outs ──────────────────────────────────────────────────

def test_a_finished_size_is_developed_once_and_a_developed_one_never():
    fin = cs.developed_blank({"length": 300, "width": 200},
                             {"folds": 4, "flange_mm": 30, "blank_basis": "finished"})
    assert (fin["length"], fin["width"], fin["changed"]) == (360, 260, True)
    assert "provisional" in fin["working"]
    dev = cs.developed_blank({"length": 1500, "width": 120},
                             {"folds": 2, "flange_mm": 20, "blank_basis": "developed"})
    assert (dev["length"], dev["width"], dev["changed"]) == (1500, 120, False)
    two = cs.developed_blank({"length": 1500, "width": 80},
                             {"folds": 2, "flange_mm": 25, "blank_basis": "finished"})
    assert (two["length"], two["width"]) == (1500, 130)        # flanges on the short side


def test_an_unstated_basis_is_priced_as_given_and_said():
    out = cs.developed_blank({"length": 500, "width": 500}, {"folds": 4})
    assert out["changed"] is False and out["length"] == 500
    assert "finished size or the flat blank" in out["note"]
    flat = cs.developed_blank({"length": 500, "width": 500}, {"folds": 0})
    assert flat["note"] == "" and flat["changed"] is False


def test_the_developed_blank_and_fold_count_reach_the_record():
    (tray,) = _parts(_sighted("Side tray", blank=(300, 200, 1.5), folds=4, flange_mm=30,
                              blank_basis="finished"))
    assert (tray["blank_length_mm"], tray["blank_width_mm"]) == (360, 260)
    assert tray["concept_finished_mm"] == {"length": 300, "width": 200}
    assert tray["concept_fold_count"] == 4
    import fold_count
    res = fold_count.press_brake_folds(tray)
    assert res["count"] == 4 and res["source"] == fold_count.CONCEPT_READ


def test_a_drawing_count_outranks_the_concept_read():
    import fold_count
    res = fold_count.press_brake_folds({"concept_fold_count": 4, "fold_count_textual": 2})
    assert res["count"] == 2 and res["source"] == fold_count.DRAWING_NOTE


def test_a_folded_part_is_never_folded_in_no_time():
    import estimator as E
    (post,) = _parts(_sighted("Slotted post", blank=(1500, 80, 2)))       # no folds given
    _, pe = _labour_ops(post)
    run = pe["process_estimate"]["run_times_min_per_unit"]["folding"]
    per_fold = E.LABOUR_RULES["folding"]["sec_per_bend"] / 60.0
    assert run >= round(per_fold, 2) > 0
    assert any("ASSUMED fold" in f for f in pe["review_flags"])
    (tray,) = _parts(_sighted("Tray", blank=(300, 200, 1.5), folds=4, flange_mm=30,
                              blank_basis="finished"))
    _, pe4 = _labour_ops(tray)
    assert pe4["process_estimate"]["run_times_min_per_unit"]["folding"] == round(4 * per_fold, 2)
    assert not any("ASSUMED fold" in f for f in pe4["review_flags"])


def test_slots_and_openings_are_cut():
    (post,) = _parts(_sighted("Slotted post", blank=(1500, 120, 2), folds=2, flange_mm=20,
                              blank_basis="developed",
                              cutouts=[{"what": "slot", "count": 44, "length_mm": 12,
                                        "width_mm": 4},
                                       {"what": "opening", "count": 1, "length_mm": 200,
                                        "width_mm": 50}]))
    internal = 44 * 2 * (12 + 4) + 2 * (200 + 50)
    assert post["manufacturing_features"]["hole_count"] == 45
    assert post["manufacturing_features"]["cut_length_mm"] == 2 * (1500 + 120) + internal
    assert post["geometry_rollup"]["estimated_cut_length_mm"] == 2 * (1500 + 120) + internal
    assert any("slot" in c for c in post["concept_cutouts"])


def test_the_read_is_asked_for_folds_flanges_basis_cutouts_and_one_line_per_size():
    assert cs.CONCEPT_PROMPT_VERSION == "c5"
    assert hashlib.sha256(cs._PROMPT.encode()).hexdigest()[:12] == cs._PROMPT_FINGERPRINT
    text = cs._PROMPT.format(n=1, ops="x")
    for word in ('"folds"', '"flange_mm"', '"blank_basis"', '"cutouts"',
                 "one line per size", "Never add flanges into a size you call finished"):
        assert word in text, word


# ── D-491: labels per component × components; application once ─────────────────────────

def test_labels_are_priced_each_and_counted_per_component():
    labels, = cs.consumable_lines(["QR component labels 20x20mm"], "J", pieces_fitted=41)
    import config
    per = config.CONCEPT_PER_COMPONENT["items_per_component"]
    assert labels["quantity"] == round(per * 41)
    assert labels["per_component"] == {"items_per_component": float(per), "components": 41}
    assert "price ONE item" in labels["research_description"]
    assert labels["items_to_apply"] == labels["quantity"]


def test_application_is_charged_once_on_the_unit():
    import estimator as E
    import config
    unit = {"part_number": "J-CPT00", "description": "unit", "quantity": 1,
            "normalized_material": "MILD STEEL", "is_assembly_parent": True,
            "assembly_children": ["a", "b"], "inferred_operations": ["assembly"],
            "pieces_fitted": 41, "items_to_apply": 41, "concept_kind": "assembly"}
    pe = E.estimate_part(dict(unit), job_quantity=200)
    per = E.LABOUR_RULES["handling"]["min_per_part"]
    want = round(per * 41 + 41 * config.CONCEPT_APPLY_MIN_PER_ITEM, 2)
    assert pe["process_estimate"]["run_times_min_per_unit"]["handling"] == want
    assert any("charged once here" in f for f in pe["review_flags"])
    src = (SRC / "file_scan.py").read_text(encoding="utf-8")
    assert '_unit["items_to_apply"] = _to_apply' in src


# ── D-492: the previous read kept, and what changed said ───────────────────────────────

def _answer(*parts):
    return {"parts": list(parts)}


def test_the_bill_round_trips_and_an_unsized_part_is_never_offered_as_size_zero(tmp_path):
    a = _answer(_sighted("Post", blank=(1500, 80, 2)), _sighted("Tray", blank=(0, 0, 1.5)))
    assert cs.save_bill(tmp_path, "JOB", a)
    prev = cs.load_previous_bill(tmp_path, "JOB")
    text = cs.previous_bill_text(prev)
    assert "Post (fabricated) x1" in text and "1500 × 80 × 2 mm" in text
    assert "Tray (fabricated) x1, MILD STEEL, no size" in text


def test_the_changes_are_listed():
    prev = {"parts": cs._bill_rows(_answer(_sighted("Post", blank=(1500, 80, 2)),
                                           _sighted("Strip", blank=(480, 35, 1))))}
    now = _answer(dict(_sighted("Post", blank=(1500, 120, 2)), quantity=6),
                  _sighted("Side strip", blank=(300, 35, 1)))
    out = cs.bill_changes(prev, now)
    assert "Post: count 1 → 6" in out
    assert "Post: size 1500 × 80 → 1500 × 120 mm" in out
    assert "added: Side strip x1" in out and "dropped: Strip x1" in out


def test_the_previous_bill_shapes_a_new_answer_but_never_the_cache_key():
    base = cs._cache_key([b"png"], "m", sheet=True, sheet_words="S")
    assert cs._cache_key([b"png"], "m", sheet=True, sheet_words="S", previous="- Post") == base
    text = cs.concept_prompt_text([b"png"], "", sheet=True, sheet_words="S", previous="- Post x6")
    assert "A PREVIOUS READ OF THIS SAME PACK" in text and "- Post x6" in text
    assert "A PREVIOUS READ" not in cs.concept_prompt_text([b"png"], "")


def test_file_scan_gives_both_reads_the_previous_bill_and_saves_the_new_one():
    src = (SRC / "file_scan.py").read_text(encoding="utf-8")
    assert "reference_pack=_ref_pack, previous=_prev_text)" in src
    assert "previous=_prev_text)" in src[src.index("_read = concept_scan.read_concept("):][:300]
    assert "CONCEPT READ CHANGED FROM THE PREVIOUS READ" in src
    assert "concept_scan.save_bill(job_folder, _bill_job, _answer)" in src
