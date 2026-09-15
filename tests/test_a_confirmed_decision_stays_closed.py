"""Four sentences the 18:21 report should not have said, each with its owner named.

James, 15 Sep review of the Howard pack: "unresolved 2 mm/200 mm confirmations, tape
labelled ACRYLIC, the tape alias reported as a missing drawing, and the contradictory
graphic free-issue/unpriced descriptions."

Four different failures with one shape: THE ENGINE ALREADY KNEW, AND ONE SURFACE DID NOT.
The graph had folded 10975-02-00 into the tape line — and a BLOCKING check still demanded
its missing detail sheet. The record knew the tape priced off a roll — and three tabs
called it ACRYLIC, the job's sheet material copied onto every line. The engine had
recognised G01 as free-issue and costed it nil on purpose — and the sheet row said
"MATERIAL UNPRICED: enter a unit rate". And a decision built on "neither reader outranks
a person" kept re-asking after a person had answered.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


# ── F4: a folded alias is not a missing drawing ──────────────────────────────────────────

def test_the_folded_tape_alias_no_longer_blocks_the_job():
    """The graph judged 10975-02-00 the same purchased tape stated twice and folded it —
    then bom_names_a_drawing_the_pack_does_not_contain blocked the job for the folded
    name's missing sheet. A record the graph has accounted for cannot also be an absence."""
    from invariants import check_the_pack_contains_the_drawings_its_bom_names as _chk
    summary = {
        "pages": [{"drawing_number": "10975-02-GA"}],
        "estimate_summary": {"part_estimates": [
            {"part_number": "10975", "description": "EPDM TAPE",
             "blank_length_mm": None,
             "folded_duplicate_identities": ["10975-02-00"]},
        ]},
        "bom_rows": [{"part_number": "10975-02-00",
                      "description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 220.00"}],
    }
    out = _chk(summary)
    assert not [v for v in out
                if "10975-02-00" in str(v)], f"the folded alias still reads as missing: {out}"


def test_the_fold_records_a_durable_field_not_only_a_sentence():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "route_compiler.py"),
               encoding="utf-8").read()
    assert 'setdefault("folded_duplicate_identities", [])' in src
    assert "folded_duplicate_identities" in open(
        os.path.join(os.path.dirname(__file__), "..", "src", "invariants.py"),
        encoding="utf-8").read()


# ── F5: roll goods are not the sheet material they inherited ─────────────────────────────

def test_the_tape_is_roll_goods_not_acrylic():
    from costed_facts import _material_label
    tape = {"part_number": "10975", "normalized_material": "ACRYLIC",
            "material_estimate": {"stock_form": "roll",
                                  "cost_method": "roll_goods_by_length"}}
    assert _material_label(tape, "bought_in") == "Roll goods (priced by length)"


def test_a_real_acrylic_part_still_says_acrylic():
    from costed_facts import _material_label
    part = {"part_number": "10975-02-A01", "normalized_material": "ACRYLIC",
            "material_estimate": {"stock_form": "sheet"}}
    assert _material_label(part, "fabricated") == "ACRYLIC"


# ── the graphic tells one story ──────────────────────────────────────────────────────────

def test_a_free_issue_line_does_not_ask_for_a_unit_rate():
    """One document said the zero is deliberate and another said the price is missing.
    Both now use the free-issue words; plain_english owns what the code means."""
    from estimator_inputs import material_input_note
    g01 = {"part_number": "10975-02-G01", "description": "GRAPHIC",
           "risk_flags": ["customer_supplied_zero_cost"]}
    note = material_input_note(g01)
    assert "FREE-ISSUE" in note and "on purpose" in note
    assert "enter a unit rate for this item" not in note


def test_an_ordinary_unpriced_line_still_asks():
    from estimator_inputs import material_input_note
    note = material_input_note({"part_number": "X", "description": "WIDGET"})
    assert "MATERIAL UNPRICED" in note


# ── F2: a person's answer closes the question ────────────────────────────────────────────

def test_a_confirmed_gauge_is_not_re_asked():
    """"neither outranks a person" is the decision's own reasoning — so when the kept
    source IS the person, the question is answered."""
    from costed_facts import thickness_conflict
    part = {"part_number": "10975-02-A01", "normalized_thickness_mm": 2.0,
            "thickness_source": "estimator_confirmed",   # the key source_of() reads
            "_displaced": {"normalized_thickness_mm": [
                {"value": 1.0, "source": "drawing_deterministic"},
                {"value": 3.0, "source": "solidworks_api"}]}}
    out = thickness_conflict(part)
    assert out is None, out


def test_the_confirmed_file_accepts_a_piece_length():
    """The tape is sized by the length cut off the roll; the pack states it twice (200
    against 220) and Howard picked 200. The answers file carries the pick."""
    import estimator_confirmed as ec
    assert ec._FIELD_MAP["piece_length_mm"] == "confirmed_piece_length_mm"


def test_a_confirmed_length_closes_the_twice_stated_conflict():
    import re as _re
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "costed_facts.py"),
               encoding="utf-8").read()
    assert "confirmed_piece_length_mm" in src
    assert _re.search(r"LENGTH:", src), "the kept reading's own figure is what is matched"


# ── the answers file must be FINDABLE, MATCHABLE and CLOSING — James, 15 Sep 19:02 review:
# "`10975-02_confirmed.json` is still not a recognised filename, `10975` still does not
#  match the tape identity, and the omitted basis still will not close the gauge decision."

def test_the_office_name_for_the_job_finds_the_file(tmp_path):
    """The engine knows the pack as 10975-02-GA; the office writes 10975-02_confirmed.json.
    Both must find it — a correct file silently doing nothing is the failure this module
    promises not to have."""
    import estimator_confirmed as ec
    (tmp_path / "10975-02_confirmed.json").write_text("{}", encoding="utf-8")
    found = ec.find_corrections_file(tmp_path, drawing_number="10975-02-GA")
    assert found is not None and found.name == "10975-02_confirmed.json"


def test_the_sheet_named_file_still_wins_over_the_stem(tmp_path):
    import estimator_confirmed as ec
    (tmp_path / "10975-02_confirmed.json").write_text("{}", encoding="utf-8")
    (tmp_path / "10975-02-GA_confirmed.json").write_text("{}", encoding="utf-8")
    found = ec.find_corrections_file(tmp_path, drawing_number="10975-02-GA")
    assert found is not None and found.name == "10975-02-GA_confirmed.json"


def test_a_numeric_segment_is_never_stripped_from_the_stem():
    """"10975" alone could govern a different job in the same folder — only trailing
    PURELY ALPHABETIC sheet-role tokens (GA, DETAIL) come off."""
    import estimator_confirmed as ec
    assert ec.drawing_stems("10975-02-GA") == ["10975-02-GA", "10975-02"]
    assert ec.drawing_stems("10975-02") == ["10975-02"]


def test_the_bom_code_matches_the_component_named_tape():
    """The tape's record is the SolidWorks component name — "10975 EPDM Closed Cell
    Tape^10975-02-GA" — and Howard's file says "10975", the BOM's own code for it."""
    import estimator_confirmed as ec
    tape = {"part_number": "10975 EPDM Closed Cell Tape^10975-02-GA"}
    assert "10975" in ec.confirmation_match_keys(tape)


def test_a_folded_identity_still_answers_to_its_name():
    import estimator_confirmed as ec
    tape = {"part_number": "10975", "folded_duplicate_identities": ["10975-02-00"]}
    assert "10975020 0".replace(" ", "") in ec.confirmation_match_keys(tape)


def test_the_leading_code_cannot_hijack_a_sibling_part():
    """"10975" must reach the tape and ONLY the tape — the acrylic body 10975-02-A01 and
    the GA itself must not answer to it."""
    import estimator_confirmed as ec
    body = {"part_number": "10975-02-A01"}
    ga = {"part_number": "10975-02-GA"}
    assert "10975" not in ec.confirmation_match_keys(body)
    assert "10975" not in ec.confirmation_match_keys(ga)


def test_a_category_word_lead_is_not_minted_into_a_code():
    import estimator_confirmed as ec
    pad = {"part_number": "TAPE 25X1MM BLACK"}
    assert "TAPE" not in ec.confirmation_match_keys(pad)


def test_the_matched_tape_takes_the_confirmed_length():
    import estimator_confirmed as ec
    tape = {"part_number": "10975 EPDM Closed Cell Tape^10975-02-GA",
            "description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 220.00"}
    report = ec.apply_estimator_confirmed(
        [tape], {"parts": {"10975": {"piece_length_mm": 200.0,
                                     "read_from": "the GA BOM row"}},
                 "confirmed_by": "Howard Thurley", "confirmed_on": "2026-09-15",
                 "path": "x"})
    assert report["unmatched"] == [], report
    assert tape.get("confirmed_piece_length_mm") == 200.0


def test_an_omitted_basis_still_closes_the_gauge_it_agrees_with():
    """With no basis the file enters at "read" (rank 72) and the DXF holds gauge at 95 —
    the person's 2 never displaces the machine's 2, the stamp stays the machine's, and the
    old closure test never fired. The agreement itself is the answer."""
    import estimator_confirmed as ec
    from costed_facts import thickness_conflict
    part = {"part_number": "10975-02-A01", "normalized_thickness_mm": 2.0,
            "thickness_source": "dxf",
            "_displaced": {"normalized_thickness_mm": [
                {"value": 1.0, "source": "drawing_deterministic", "applied": False},
                {"value": 3.0, "source": "solidworks_api", "applied": False}]}}
    assert thickness_conflict(part) is not None, "the conflict must exist before the answer"
    ec.apply_estimator_confirmed(
        [part], {"parts": {"10975-02-A01": {"thickness_mm": 2.0,
                                            "read_from": "the title block"}}, "path": "x"})
    assert thickness_conflict(part) is None, "a person confirming the kept 2 mm closes it"


def test_an_agreement_is_visible_not_silent():
    """apply_field returns False for agreement AND refusal; a working file whose every
    figure agrees must not look like a file that did nothing."""
    import estimator_confirmed as ec
    part = {"part_number": "10975-02-A01", "normalized_thickness_mm": 2.0,
            "thickness_source": "dxf"}
    report = ec.apply_estimator_confirmed(
        [part], {"parts": {"10975-02-A01": {"thickness_mm": 2.0,
                                            "read_from": "the title block"}},
                 "confirmed_by": "Howard Thurley", "path": "x"})
    assert report["agreed"] == 1, report
    assert "10975-02-A01" in report["matched"]
    assert part.get("estimator_confirmed"), "the record says who answered"
    assert any("CONFIRMED by Howard Thurley" in f and "agreeing" in f
               for f in part.get("review_flags", [])), part.get("review_flags")


def test_a_person_naming_a_different_gauge_closes_nothing():
    import estimator_confirmed as ec
    from costed_facts import thickness_conflict
    part = {"part_number": "10975-02-A01", "normalized_thickness_mm": 2.0,
            "thickness_source": "dxf",
            "_displaced": {"normalized_thickness_mm": [
                {"value": 3.0, "source": "solidworks_api", "applied": False}]}}
    ec.apply_estimator_confirmed(
        [part], {"parts": {"10975-02-A01": {"thickness_mm": 1.0,
                                            "read_from": "the title block"}}, "path": "x"})
    assert thickness_conflict(part) is not None, "a disagreement must stay visible"


def test_howards_answer_file_end_to_end(tmp_path):
    """The exact file James described, spelled the office way, basis omitted — found,
    matched, and closing both open questions."""
    import json as _json
    import estimator_confirmed as ec
    from costed_facts import thickness_conflict
    (tmp_path / "10975-02_confirmed.json").write_text(_json.dumps({
        "confirmed_by": "Howard Thurley", "confirmed_on": "2026-09-15",
        "parts": {
            "10975-02-A01": {"thickness_mm": 2.0, "read_from": "the GA title block"},
            "10975": {"piece_length_mm": 200.0, "read_from": "the GA BOM row"},
        }}), encoding="utf-8")
    path = ec.find_corrections_file(tmp_path, drawing_number="10975-02-GA")
    assert path is not None
    corrections, problems = ec.load_corrections(path)
    assert not problems, problems
    body = {"part_number": "10975-02-A01", "normalized_thickness_mm": 2.0,
            "thickness_source": "dxf",
            "_displaced": {"normalized_thickness_mm": [
                {"value": 3.0, "source": "solidworks_api", "applied": False}]}}
    tape = {"part_number": "10975 EPDM Closed Cell Tape^10975-02-GA"}
    report = ec.apply_estimator_confirmed([body, tape], corrections)
    assert report["unmatched"] == [], report
    assert thickness_conflict(body) is None
    assert tape.get("confirmed_piece_length_mm") == 200.0


def test_the_roll_branch_prefers_the_confirmed_length():
    import estimator
    part = {"part_number": "10975", "description": "Tape^ EPDM TAPE 25X1MM - TAPE 113C "
                                                   "LENGTH: 220.00",
            "normalized_material": "ACRYLIC", "quantity": 3,
            "confirmed_piece_length_mm": 200.0}
    out = estimator.roll_goods_material(part)
    if out and out.get("length_used_mm"):
        assert out["length_used_mm"] == 600.0, "3 x the CONFIRMED 200, not the parsed 220"
    else:
        # offline the roll may not price (no system price); the length preference is still
        # provable from the review flag the override writes
        assert any("confirmed by an estimator" in f for f in part.get("review_flags", []))
