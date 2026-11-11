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
    graphic, unrouted = _parts(_sighted("Graphic header", kind="graphic"),
                               _sighted("Graphic panel", ops=()))
    assert _labour_ops(graphic)[0] == ["handling"]
    assert _labour_ops(unrouted)[0] == ["handling"]


def test_an_explicitly_made_part_with_no_size_stays_made():
    """Review of D-489: missing geometry must not turn a made part into a purchase."""
    (unsized,) = _parts(_sighted("Graphic panel", blank=(0, 0, 2)))
    ops, pe = _labour_ops(unsized)
    assert {"laser_cutting", "folding", "powder_coating"} <= set(ops)
    assert not unsized.get("special_finish_item")
    import estimator as E
    assert E._is_made_line(pe)              # so the rescue asks for raw material only (D-485)


def test_the_evidenced_make_test_needs_all_three():
    import bought_in_policy as bp
    (made,) = _parts(_sighted("Rear graphic panel"))
    assert bp.read_states_a_made_part(made)
    assert not bp.read_states_a_made_part(dict(made, concept_kind="bought_in"))
    assert not bp.read_states_a_made_part(dict(made, normalized_material="PRINTED_PAPER"))
    assert bp.read_states_a_made_part(dict(made, blank_width_mm=0))        # size not required
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
    assert any(f.startswith("FOLD ALLOWANCE") for f in pe["review_flags"])
    assert any("charged as an ALLOWANCE, not a count" in f for f in pe["review_flags"])
    assert not any("0 fold(s) charged" in f for f in pe["review_flags"])
    (tray,) = _parts(_sighted("Tray", blank=(300, 200, 1.5), folds=4, flange_mm=30,
                              blank_basis="finished"))
    _, pe4 = _labour_ops(tray)
    assert pe4["process_estimate"]["run_times_min_per_unit"]["folding"] == round(4 * per_fold, 2)
    assert not any("ALLOWANCE" in f for f in pe4["review_flags"])
    assert any("from the concept read's provisional count" in f for f in pe4["review_flags"])


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
    # c5 added these; c6 (D-528, a part's stock form and sizes) keeps every one of them.
    assert cs.CONCEPT_PROMPT_VERSION in ("c5", "c6", "c7", "c8")
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
    # Priced per item AT THE JOB'S VOLUME (D-500), never a single-item retail listing.
    assert "at this job's volume" in labels["research_description"]
    assert "never a single-item retail listing" in labels["research_description"]
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
    assert "Post: count 1 → 6 (no reason given)" in out
    assert "Post: size 1500 × 80 → 1500 × 120 mm (no reason given)" in out
    assert "added: Side strip x1" in out and "dropped: Strip x1" in out


def test_the_previous_bill_shapes_a_new_answer_but_never_the_cache_key():
    base = cs._cache_key([b"png"], "m", sheet=True, sheet_words="S")
    assert cs._cache_key([b"png"], "m", sheet=True, sheet_words="S", previous="- Post") == base
    text = cs.concept_prompt_text([b"png"], "", sheet=True, sheet_words="S", previous="- Post x6")
    assert "A PREVIOUS READ OF THIS SAME PACK" in text and "- Post x6" in text
    assert "A PREVIOUS READ" not in cs.concept_prompt_text([b"png"], "")


def test_file_scan_gives_both_reads_the_previous_bill_and_saves_the_new_one():
    src = (SRC / "file_scan.py").read_text(encoding="utf-8")
    sheet = src[src.index("_sr = concept_scan.read_sheet_concept("):][:700]
    render = src[src.index("_read = concept_scan.read_concept("):][:400]
    for call in (sheet, render):
        assert "previous=_prev_text" in call
        assert "previous_base_key=" in call and "previous_read_key=" in call
    assert "CONCEPT READ CHANGED FROM THE PREVIOUS READ" in src
    saved = src[src.index("concept_scan.save_bill(job_folder, _bill_job, _answer"):][:300]
    assert "records=_sighted" in saved and "read_key=" in saved
    # saved AFTER the answers file is applied, so approvals are marked on the bill
    assert src.index("_ec2.apply_estimator_confirmed(_sighted") < src.index(
        "concept_scan.save_bill(job_folder, _bill_job, _answer")


# ── Review of D-489..D-492: four points tightened (D-493) ──────────────────────────────

def _slotted_post(cutouts=True):
    extra = dict(folds=2, flange_mm=20, blank_basis="developed")
    if cutouts:
        extra["cutouts"] = [{"what": "slot", "count": 44, "length_mm": 12, "width_mm": 4}]
    return _sighted("Slotted corner post", blank=(1500, 120, 2), **extra)


def test_sighted_cut_outs_reach_the_charged_cutting_and_never_assume_punch_tooling():
    from wb_populate import costed_geometry_value
    slotted, plain = _parts(_slotted_post(), dict(_slotted_post(False), name="Plain post"))
    ops_s, pe_s = _labour_ops(slotted)
    ops_p, pe_p = _labour_ops(plain)
    assert "punch" not in ops_s and "laser_cutting" in ops_s
    assert any(f.startswith("PUNCH NOT ASSUMED") for f in pe_s["review_flags"])
    run_s = pe_s["process_estimate"]["run_times_min_per_unit"]["laser_cutting"]
    run_p = pe_p["process_estimate"]["run_times_min_per_unit"]["laser_cutting"]
    assert run_s > run_p                                       # the slots are charged
    # The workbook's Laser Rate Calculator inputs: S = holes, T = cut length - perimeter.
    assert costed_geometry_value(pe_s, "hole_count", "estimated_hole_count") == 44
    cut = float(costed_geometry_value(pe_s, "cut_length_mm", "estimated_cut_length_mm"))
    assert round(cut - 2 * (1500 + 120), 1) == 44 * 2 * (12 + 4)


def test_a_measured_dense_hole_field_still_punches():
    import estimator as E
    pe = E.estimate_part({"part_number": "P-1", "description": "PEG PANEL", "quantity": 1,
                          "normalized_material": "MILD STEEL", "normalized_thickness_mm": 1.5,
                          "blank_length_mm": 600, "blank_width_mm": 400,
                          "normalized_geometry": {"blank_length_mm": 600, "blank_width_mm": 400},
                          "geometry_rollup": {"estimated_hole_count": 120,
                                              "estimated_pierce_count": 120},
                          "inferred_operations": ["laser_cutting"]}, job_quantity=10)
    assert "punch" in (pe.get("labour_estimate") or {}).get("costs_gbp", {})


def test_the_baseline_marks_approved_values_and_calls_the_rest_provisional(tmp_path, monkeypatch):
    from source_precedence import apply_field
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "cache" / "vision_concept")
    a = _answer(_sighted("Post", blank=(1500, 80, 2)), _sighted("Header", blank=(500, 80, 2)))
    recs = _parts(*a["parts"])
    apply_field(recs[0], "quantity", 6, "estimator_confirmed", note="counted on the brief")
    cs.save_bill(tmp_path / "Boots" / "JOB", "JOB", a, records=recs)
    text = cs.previous_bill_text(cs.load_previous_bill(tmp_path / "Boots" / "JOB", "JOB"))
    assert "Post (fabricated) x1" in text and "APPROVED by the estimator: count" in text
    assert "Header (fabricated) x1, MILD STEEL, 500 × 80 × 2 mm [provisional AI assumption]" in text
    section = cs._PREVIOUS_SECTION.format(bill=text)
    assert "BASELINE, not evidence" in section and "keep it exactly" in section
    assert "old value, the new value and the reason" in section


def test_a_change_shows_old_new_and_why_and_an_approved_one_is_called_out():
    prev = {"parts": [dict(r, approved=(["size"] if r["name"] == "Post" else []))
                      for r in cs._bill_rows(_answer(_sighted("Post", blank=(1500, 80, 2)),
                                                     _sighted("Tray", blank=(300, 200, 1.5))))]}
    now = _answer(_sighted("Post", blank=(1500, 120, 2), why_size="the brief's 120 mm profile"),
                  _sighted("Tray", blank=(360, 260, 1.5)))
    out = cs.bill_changes(prev, now)
    post = next(c for c in out if c.startswith("Post: size"))
    assert "1500 × 80 → 1500 × 120 mm" in post and "the brief's 120 mm profile" in post
    assert "AN APPROVED VALUE CHANGED; the estimator's stands" in post
    tray = next(c for c in out if c.startswith("Tray: size"))
    assert "no reason given" in tray and "APPROVED" not in tray


def test_an_unchanged_read_is_reused_and_a_new_baseline_is_a_new_question(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "vision_concept")
    monkeypatch.setattr(cs, "_call_vision_llm",
                        lambda pngs, model, brief, **kw: calls.append(kw.get("previous", ""))
                        or '{"parts": [{"name": "Post", "kind": "fabricated", "quantity": %d}]}'
                        % len(calls))
    brief = "A unit of posts."
    first = cs.read_concept([], brief=brief)                     # no baseline yet
    assert calls == [""] and first["read_key"] == first["base_key"]
    # The bill that answer produced, offered back with the same question: reused, not asked.
    again = cs.read_concept([], brief=brief, previous="- Post x1",
                            previous_base_key=first["base_key"],
                            previous_read_key=first["read_key"])
    assert len(calls) == 1 and again["baseline"] == "unchanged read reused"
    # A seeded or edited baseline: a new interpretation, asked once and then cached.
    seeded = cs.read_concept([], brief=brief, previous="- Post x6 [APPROVED]")
    assert len(calls) == 2 and calls[-1] == "- Post x6 [APPROVED]"
    assert seeded["read_key"] != seeded["base_key"]
    cs.read_concept([], brief=brief, previous="- Post x6 [APPROVED]")
    assert len(calls) == 2                                       # same baseline replays
    cs.read_concept([], brief=brief, previous="- Post x8")
    assert len(calls) == 3                                       # a different one is asked


def test_the_bill_survives_a_re_stage_and_a_new_selection_wins(tmp_path, monkeypatch):
    import importlib.util
    import types
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location(
        "staging_under_test", ROOT / "sdi-intelligence-backend" / "staging.py")
    staging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staging)
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "brief.pdf").write_bytes(b"%PDF-1.4 brief")
    first = staging.stage([str(pack / "brief.pdf")], client="Boots", drawing="JOB")
    job = Path(first["folder"])
    (job / "JOB_concept_bill.json").write_text('{"parts": [1]}', encoding="utf-8")
    (job / "JOB_estimator_dimensions.json").write_text('{"parts": {}}', encoding="utf-8")
    (job / "stale.pdf").write_bytes(b"%PDF-1.4 stale")
    again = staging.stage([str(pack / "brief.pdf")], client="Boots", drawing="JOB")
    names = sorted(p.name for p in job.iterdir())
    assert "stale.pdf" not in names                                  # drawings still replaced
    assert {"JOB_concept_bill.json", "JOB_estimator_dimensions.json"} <= set(names)
    assert set(again["job_data_kept"]) == {"JOB_concept_bill.json",
                                           "JOB_estimator_dimensions.json"}


def test_the_engine_also_keeps_its_own_copy_outside_the_staged_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "engine" / "cache" / "vision_concept")
    job = tmp_path / "staged" / "Boots" / "JOB"
    job.mkdir(parents=True)
    cs.save_bill(job, "JOB", _answer(_sighted("Post", blank=(1500, 80, 2))))
    (job / "JOB_concept_bill.json").unlink()                         # a re-stage emptied it
    assert (tmp_path / "engine" / "cache" / "concept_bills" / "Boots__JOB.json").is_file()
    assert cs.load_previous_bill(job, "JOB")["parts"][0]["name"] == "Post"


# ── D-494: measured holes establish the holes, not the tooling ───────────────────────────

def _peg_panel(**over):
    p = {"part_number": "P-1", "description": "PEG PANEL", "quantity": 1,
         "normalized_material": "MILD STEEL", "normalized_thickness_mm": 1.5,
         "blank_length_mm": 600, "blank_width_mm": 400,
         "normalized_geometry": {"blank_length_mm": 600, "blank_width_mm": 400},
         "geometry_rollup": {"estimated_hole_count": 120, "estimated_pierce_count": 120},
         "inferred_operations": ["laser_cutting"]}
    p.update(over)
    return p


def test_a_punch_switch_is_said_as_a_provisional_process_assumption():
    import estimator as E
    pe = E.estimate_part(_peg_panel(), job_quantity=10)
    assert "punch" in (pe.get("labour_estimate") or {}).get("costs_gbp", {})
    assert any(f.startswith("PUNCH — A PROVISIONAL PROCESS ASSUMPTION") and "not verified" in f
               for f in pe["review_flags"])


def test_stated_punch_limits_are_checked(monkeypatch):
    import config
    import estimator as E
    monkeypatch.setitem(config.PUNCH_RECOGNITION, "max_gauge_mm", 1.2)
    pe = E.estimate_part(_peg_panel(), job_quantity=10)
    costs = (pe.get("labour_estimate") or {}).get("costs_gbp", {})
    assert "punch" not in costs and "laser_cutting" in costs
    assert any(f.startswith("PUNCH NOT USED") and "1.5 mm is over" in f for f in pe["review_flags"])
    monkeypatch.setitem(config.PUNCH_RECOGNITION, "max_gauge_mm", None)
    monkeypatch.setitem(config.PUNCH_RECOGNITION, "max_tool_mm", 10)
    pe2 = E.estimate_part(_peg_panel(hole_sizes_mm=[6, 12]), job_quantity=10)
    assert "punch" not in (pe2.get("labour_estimate") or {}).get("costs_gbp", {})
    assert any("12 mm hole is over the largest stated punch tool" in f for f in pe2["review_flags"])


def test_the_brief_uses_the_manual_for_constraints_not_its_examples():
    text = (ROOT / "docs" / "briefs" / "KWellnessFSDU.md").read_text(encoding="utf-8")
    assert "use the manual for applicable requirements and constraints" in text
    assert "never for parts, dimensions or loads" not in text
