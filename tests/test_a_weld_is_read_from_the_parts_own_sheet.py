"""12173-02 Card Spinner (M&S), 1 Oct 17:34 book, review of D-378..D-382: a weld is read from a
part's own sheet, and the pack's weld specification is not one.

1. The weld-symbol reader returned nothing for every sheet of the 12173-03 pack although 201,
   202, 203, 04M and 05M draw ISO fillet callouts: pdfplumber writes their solid strokes as
   dash ([], 0), the fillets are drawn as separate strokes, and the weld-all-round circle at
   the arrow junction would read as a spot weld once the first was fixed.
2. The inferred-weld decision said "no weld note or symbol on the drawing" as a literal, beside
   the extract's own "weld symbols ... on pages 6-8".
3. The parent-weld question (D-382) said its sheet "shows no arc-weld symbol" (the reader was
   blind there) and counted a seam as an arc weld; it is a decision only where money rides on
   it.
4. A DXF named <part>-<n> is read as piece n only where nothing in the job names <part>-<n> as
   an item; a numbered piece is never bound to a handed variant.
5. The title-block reader cut "12173-07-2-01M" to "12173-07-2" and "12173-04-02M-H" to
   "12173-04-02M", pooling members' sheets under a key that is no part.
6. The border's "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED" painted a weld cue onto
   29 parts (tab-and-slot pocket sides, the rack, meshes, risers, an MFC back). It says how a
   weld is made, not that a part is welded.
"""
from pathlib import Path
import math
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf                                      # noqa: E402
import drawing_facts as df                                     # noqa: E402
import drawing_job_merge as d                                  # noqa: E402
import extractor_patterns as ep                                # noqa: E402
import weld_symbols as ws                                      # noqa: E402

SOLID = ([], 0)


def _line(x0, y0, x1, y1, dash=None):
    return {"x0": min(x0, x1), "x1": max(x0, x1), "top": min(y0, y1), "bottom": max(y0, y1),
            "pts": [(x0, y0), (x1, y1)], "dash": dash}


def _circle(cx, cy, dia):
    pts = [(cx + dia / 2 * math.cos(a / 20 * 2 * math.pi), cy + dia / 2 * math.sin(a / 20 * 2 * math.pi))
           for a in range(21)]
    return {"x0": cx - dia / 2, "x1": cx + dia / 2, "top": cy - dia / 2, "bottom": cy + dia / 2,
            "pts": pts}


def _callout(x, y, with_id=True, solid=None):
    """Reference line 15.7 long with a leader from its right end; ISO id line 2.75 below."""
    lines = [_line(x, y, x + 15.7, y, dash=solid), _line(x + 15.7, y, x + 25.3, y - 66.3, dash=solid)]
    if with_id:
        lines.append(_line(x, y + 2.75, x + 15.7, y + 2.75, dash=([3.6, 1.8], 2.064)))
    return lines


def _stroke_fillet(x, y, solid=None):
    """201's own drawing: a vertical leg standing on the line and a slant back down to it."""
    return [_line(x + 5.5, y - 5.3, x + 5.5, y, dash=solid),
            _line(x + 5.5, y - 5.3, x + 10.2, y, dash=solid)]


# ── 1. the reader ────────────────────────────────────────────────────────────────────────

def test_a_solid_line_with_an_empty_dash_pattern_is_solid():
    assert ws._dashed({"dash": SOLID}) is False and ws._dashed({"dash": None}) is False
    assert ws._dashed({"dash": ([3.6, 1.8], 2.0)}) is True
    lines = _callout(100, 100, solid=SOLID) + _stroke_fillet(100, 100, solid=SOLID)
    assert [g["kind"] for g in ws.read_weld_symbols(lines, [])] == ["fillet"]


def test_a_fillet_drawn_as_strokes_is_a_fillet():
    got = ws.read_weld_symbols(_callout(100, 100) + _stroke_fillet(100, 100), [])
    assert [g["kind"] for g in got] == ["fillet"] and got[0]["all_round"] is False


def test_strokes_without_the_iso_identification_line_are_not_a_fillet():
    assert ws.read_weld_symbols(_callout(100, 100, with_id=False) + _stroke_fillet(100, 100), []) == []


def test_the_all_round_circle_at_the_junction_is_not_a_spot_weld():
    got = ws.read_weld_symbols(_callout(100, 100) + _stroke_fillet(100, 100),
                               [_circle(115.7, 100, 4.3)])
    assert [g["kind"] for g in got] == ["fillet"] and got[0]["all_round"] is True
    assert ws.only_spot_welds(ws.count_by_kind(got)) == 0


def test_a_circle_past_the_line_end_is_not_a_spot():
    """The spot range stays the line's own: a hole in line with the reference is not a weld."""
    got = ws.read_weld_symbols(_callout(100, 100), [_circle(115.7 + 3.0, 100, 4.7)])
    assert [g["kind"] for g in got] == ["unclassified"]
    assert ws.only_spot_welds(ws.count_by_kind(got)) == 0


def test_a_spot_circle_mid_line_still_reads_spot():
    got = ws.read_weld_symbols(_callout(100, 100, solid=SOLID), [_circle(107.9, 100, 4.7)])
    assert [g["kind"] for g in got] == ["spot"] and got[0]["all_round"] is False


# ── 2/3. what the reading states, and the sentence about it ──────────────────────────────

def test_the_sentence_reports_a_reading_never_an_absence():
    assert ws.describe_weld_symbols(None) == "its own sheet was not read for weld symbols"
    assert ws.describe_weld_symbols({}, [6]) == \
        "the weld-symbol reader named no weld symbol on its own sheet (p.6)"
    assert "named no weld symbol" in ws.describe_weld_symbols({"unclassified": 3}, [4])
    assert ws.describe_weld_symbols({"fillet": 2, "unclassified": 1}, [6]) == \
        "the weld-symbol reader found 2 fillet weld symbol(s) on its own sheet (p.6)"


def test_only_a_fillet_is_an_arc_weld():
    assert ws.arc_weld_symbols({"fillet": 2, "seam": 3, "spot": 1, "unclassified": 4}) == 2
    assert ws.arc_weld_symbols({"seam": 3}) == 0


def test_a_sheet_with_fillets_states_the_weld_and_a_seam_does_not():
    parts = [{"part_number": "X-101", "inferred_operations": ["welding"]}, {"part_number": "X-102"}]
    ws.apply_to_parts(parts, {"X-101": {"counts": {"fillet": 4}, "pages": [4], "text": ""},
                              "X-102": {"counts": {"seam": 2}, "pages": [5], "text": ""}})
    assert parts[0]["operation_sources"]["welding"] == "drawing_deterministic"
    assert "welding" in parts[0]["textual_operations"] and parts[0]["weld_symbol_pages"] == [4]
    assert any("found 4 fillet" in f for f in parts[0]["review_flags"])
    assert "welding" not in (parts[1].get("textual_operations") or [])
    assert parts[1]["weld_symbols"] == {"seam": 2} and parts[1]["weld_symbol_pages"] == [5]


def _frame_sheets(parent_counts):
    return {
        "W-201": {"finish": "POWDER COATED - MATT", "text": "W-202W-203", "counts": parent_counts,
                  "pages": [6]},
        "W-202": {"finish": "WELDED", "text": "", "counts": {"fillet": 1}, "pages": [7]},
        "W-203": {"finish": "WELDED", "text": "", "counts": {"fillet": 1}, "pages": [8]},
    }


def test_a_parent_whose_own_sheet_draws_the_joint_is_welded_by_its_symbols():
    parts = [{"part_number": k} for k in ("W-201", "W-202", "W-203")]
    sheets = _frame_sheets({"fillet": 2})
    ws.apply_to_parts(parts, sheets)
    got = ws.apply_finish_welds(parts, sheets)
    assert got["joined_by_symbol"] == ["W-201"] and got["questioned"] == []
    assert parts[0]["operation_sources"]["welding"] == "drawing_deterministic"
    assert "operations_ruled_out" not in parts[0]
    assert any("found 2 fillet" in f and "W-202, W-203" in f for f in parts[0]["review_flags"])


def test_a_seam_or_an_unnamed_mark_does_not_settle_the_parent():
    for counts, said in (({"seam": 1}, "found 1 seam weld symbol(s) on its own sheet (p.6)"),
                         ({"unclassified": 3}, "named no weld symbol on its own sheet (p.6)"),
                         ({}, "named no weld symbol on its own sheet (p.6)")):
        parts = [{"part_number": k} for k in ("W-201", "W-202", "W-203")]
        sheets = _frame_sheets(counts)
        ws.apply_to_parts(parts, sheets)
        assert ws.apply_finish_welds(parts, sheets)["questioned"] == ["W-201"]
        assert "welding" not in (parts[0].get("textual_operations") or []), counts
        q = parts[0]["manufacturing_questions"][0]
        assert "the weld-symbol reader " + said in q["issue"]
        assert "shows no" not in q["issue"] and "unclassified" not in q["issue"]
        assert q["charged_operations"] == ["welding", "spot_welding", "dress_welds"]


def _src(rec, rows, decisions=()):
    return {"estimate_summary": {
        "part_estimates": [{"part_number": rec["part_number"], "quantity": 1}],
        "canonical_route_shadow": {"decisions": list(decisions)},
        "final_estimate": {"labour_rows": [
            {"operation": o, "total_value_gbp": v, "workbook_row": n} for n, o, v, _ in rows]},
        "workbook_labour": {"rows": [
            {"workbook_row": n, "engine_operations": [e], "part_numbers": [rec["part_number"], "W-202"]}
            for n, _, _, e in rows]}},
        "manufacturing_writeup": {"parts": [rec]}}


def _parent_record():
    parts = [{"part_number": k} for k in ("W-201", "W-202", "W-203")]
    ws.apply_finish_welds(parts, _frame_sheets({}))
    return parts[0]


def test_the_parents_question_carries_its_weld_rows_money_once():
    rec = _parent_record()
    guess = {"operation": "welding", "status": "required", "source": "inference",
             "target_id": "W-201", "evidence": ""}
    src = _src(rec, [(179, "Weld (CO2)", 25.06, "welding"), (182, "Dress Welds", 16.25, "dress_welds")],
               [guess])
    ds = [x for x in cf.costed_job(src)["decisions_required"]
          if x.get("part") == "W-201" and x.get("kind") == "manufacturing_decision"]
    assert len(ds) == 1, "asked once: the inferred-weld decision does not ask it again"
    assert abs(ds[0]["gbp_at_stake"] - 41.31) < 0.01
    assert "Estimate rows 179, 182" in ds[0]["assumption"]


def test_an_uncharged_parent_is_flagged_not_asked():
    rec = _parent_record()
    src = _src(rec, [])
    assert not [x for x in cf.costed_job(src)["decisions_required"]
                if x.get("part") == "W-201" and x.get("kind") == "manufacturing_decision"]
    assert any("WELD ON THIS ASSEMBLY NOT SETTLED" in f for f in rec["review_flags"])


def test_an_assembly_with_no_line_of_its_own_still_asks():
    rec = _parent_record()
    src = _src(rec, [(179, "Weld (CO2)", 25.06, "welding")])
    src["estimate_summary"]["part_estimates"] = [{"part_number": "W-202", "quantity": 1}]
    ds = [x for x in cf.costed_job(src)["decisions_required"]
          if x.get("part") == "W-201" and x.get("kind") == "manufacturing_decision"]
    assert len(ds) == 1 and abs(ds[0]["gbp_at_stake"] - 25.06) < 0.01


def _guess(rec):
    return {"estimate_summary": {
        "part_estimates": [{"part_number": "X-101"}],
        "canonical_route_shadow": {"decisions": [{
            "operation": "welding", "status": "required", "source": "inference",
            "target_id": "X-101", "evidence": ""}]}},
        "manufacturing_writeup": {"parts": [rec]}}


def test_the_inferred_weld_sentence_is_computed_from_the_symbol_record():
    for rec, want in (
            ({"part_number": "X-101"}, "was not read for weld symbols"),
            ({"part_number": "X-101", "weld_symbols": {}, "weld_symbol_pages": [4]},
             "named no weld symbol on its own sheet (p.4)"),
            ({"part_number": "X-101", "weld_symbols": {"unclassified": 2},
              "weld_symbol_pages": [4]}, "named no weld symbol")):
        dd = [x for x in cf.costed_job(_guess(rec))["decisions_required"]
              if "inferred, not drawn" in x["issue"]][0]
        assert "no weld note or symbol on the drawing" not in dd["assumption"]
        assert want in dd["assumption"] and "quotes no weld note" in dd["assumption"]
        assert "unclassified" not in dd["assumption"]


# ── 4. a numbered piece or an item of its own ────────────────────────────────────────────

def _flat(path, w, h):
    import ezdxf
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True)
    doc.saveas(path)


def _merge(tmp_path, files, parts, bom_rows=None):
    for name, w, h in files:
        _flat(tmp_path / name, w, h)
    s = {"manufacturing_writeup": {"parts": parts}, "pages": []}
    if bom_rows is not None:
        s["document_analysis"] = {"bom_rows": bom_rows}
    out = d.augment_summary_with_dxf(s, sorted(tmp_path.glob("*.DXF")), reestimate=False)
    return {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}, out["dxf_augmentation"]


def test_a_sibling_item_makes_the_piece_reading_a_question(tmp_path):
    got, rep = _merge(tmp_path, [("9999-01-04M-1_1.5mm MS_revA.DXF", 600, 400),
                                 ("9999-01-04M-2_1.5mm MS_revA.DXF", 900, 400)],
                      [{"part_number": "9999-01-04M", "quantity": 1},
                       {"part_number": "9999-01-04M-2", "quantity": 1}])
    assert not got["9999-01-04M"].get("geometry_source")
    assert got["9999-01-04M-2"].get("geometry_source")
    q = got["9999-01-04M"]["manufacturing_questions"][0]
    assert q["subject"] == "dxf_identity" and q["gbp_parts"] == []
    assert "9999-01-04M-1_1.5mm MS_revA.DXF" in q["issue"] and "9999-01-04M-2 is a part" in q["assumption"]
    assert any(a["reason"] == "numbered_piece_or_separate_item_unresolved" for a in rep["ambiguous_dxf"])


def test_the_same_number_padded_is_the_exact_item(tmp_path):
    got, _ = _merge(tmp_path, [("9999-01-04M-1_1.5mm MS_revA.DXF", 600, 400)],
                    [{"part_number": "9999-01-04M", "quantity": 1},
                     {"part_number": "9999-01-04M-01", "quantity": 1}])
    assert got["9999-01-04M-01"].get("geometry_source")
    assert not got["9999-01-04M"].get("geometry_source")


def test_a_parts_list_code_in_the_family_makes_it_a_question(tmp_path):
    got, _ = _merge(tmp_path, [("9999-01-04M-1_1.5mm MS_revA.DXF", 600, 400)],
                    [{"part_number": "9999-01-04M", "quantity": 1}],
                    [{"part_number": "9999-01-04M-2", "description": "FRAME",
                      "bom_parent": "9999-01-GA"}])
    assert not got["9999-01-04M"].get("geometry_source")
    assert any("NOT ATTACHED" in f for f in got["9999-01-04M"]["review_flags"])


def test_differing_unsized_pieces_are_costed_and_asked(tmp_path):
    got, _ = _merge(tmp_path, [("9999-01-04M-1_1.5mm MS_revA.DXF", 600, 400),
                               ("9999-01-04M-2_1.5mm MS_revA.DXF", 900, 400)],
                    [{"part_number": "9999-01-04M", "quantity": 1}])
    assert {"9999-01-04M-01", "9999-01-04M-02"} <= set(got)
    q = got["9999-01-04M"]["manufacturing_questions"][0]
    assert q["gbp_parts"] == ["9999-01-04M-01", "9999-01-04M-02"]
    assert got["9999-01-04M-01"]["dxf_minted_piece_of"] == "9999-01-04M"


def test_a_numbered_piece_never_lands_on_a_handed_variant(tmp_path):
    got, _ = _merge(tmp_path, [("9999-04-02M-1_1mm MS_revA.DXF", 600, 400),
                               ("9999-04-02M-2_1mm MS_revA.DXF", 300, 200)],
                    [{"part_number": "9999-04-02M", "quantity": 1},
                     {"part_number": "9999-04-02M-H", "quantity": 1}])
    assert not got["9999-04-02M-H"].get("geometry_source")
    assert {"9999-04-02M-01", "9999-04-02M-02"} <= set(got)


def test_the_parents_own_size_rows_corroborate_the_layers(tmp_path):
    rows = [{"part_number": "", "description": "626 x 626 x 25 mm", "quantity": 1,
             "bom_item_no": i, "bom_parent": "12173-03-01J", "bom_parent_known": True}
            for i in ("1", "2")]
    got, rep = _merge(tmp_path, [("12173-03-01J-1_25mm MDF_revA.DXF", 626, 626),
                                 ("12173-03-01J-2_25mm MDF_revA.DXF", 626, 626)],
                      [{"part_number": "12173-03-01J", "description": "BASE", "quantity": 1}], rows)
    assert {"12173-03-01J-01", "12173-03-01J-02"} <= set(got)
    flags = " ".join(got["12173-03-01J"]["review_flags"])
    assert "sizes the pieces: 626 x 626 x 25 mm" in flags and "costed as 12173-03-01J-01" in flags
    assert "no row of its parts lists is named 12173-03-01J-1" in flags
    assert not got["12173-03-01J"].get("manufacturing_questions")
    assert any(a["reason"] == "numbered_pieces_promoted" for a in rep["ambiguous_dxf"])
    assert any("piece of 12173-03-01J" in f for f in got["12173-03-01J-02"]["review_flags"])


def test_item_numbers_of_a_coded_parts_list_do_not_corroborate(tmp_path):
    rows = [{"part_number": "FIXING49", "description": "M5 NUT", "bom_item_no": "1",
             "bom_parent": "9999-01-01A"},
            {"part_number": "9999-01-02M", "description": "BRACKET", "bom_item_no": "2",
             "bom_parent": "9999-01-01A"}]
    got, _ = _merge(tmp_path, [("9999-01-01A-1_2mm MS_revA.DXF", 600, 400),
                               ("9999-01-01A-2_2mm MS_revA.DXF", 600, 400)],
                    [{"part_number": "9999-01-01A", "quantity": 1}], rows)
    assert "does not size them" in " ".join(got["9999-01-01A"]["review_flags"])


def test_a_single_numbered_file_is_attached_and_named(tmp_path):
    got, _ = _merge(tmp_path, [("9999-03-01J-2_25mm MDF_revA.DXF", 626, 626)],
                    [{"part_number": "9999-03-01J", "description": "BASE", "quantity": 1}])
    flags = " ".join(got["9999-03-01J"]["review_flags"])
    assert got["9999-03-01J"].get("geometry_source")
    assert "read as numbered piece 2 of 9999-03-01J" in flags and "Only one numbered file" in flags


def test_a_model_component_named_like_a_costed_piece_is_asked():
    parts = [{"part_number": "9999-03-01J", "dxf_pieces": [
        {"dxf": "9999-03-01J-1_25mm MDF_revA.DXF", "piece": "1", "costed_as": "9999-03-01J-01"}]}]
    assert d.recheck_dxf_pieces_against_model(parts, ["9999-03-01J-1"]) == ["9999-03-01J"]
    q = parts[0]["manufacturing_questions"][0]
    assert q["gbp_parts"] == ["9999-03-01J-01"] and "the model holds a component 9999-03-01J-1" in q["assumption"]
    assert d.recheck_dxf_pieces_against_model(
        [{"part_number": "9999-03-01J", "dxf_pieces": parts[0]["dxf_pieces"]}], ["9999-03-02J"]) == []


def test_a_dxf_identity_question_carries_the_pieces_money():
    q = {"issue": "Are A and B numbered pieces of P, or flats of items of their own?",
         "assumption": "costed", "action": "say", "subject": "dxf_identity",
         "gbp_parts": ["P-01", "P-02"]}
    src = {"estimate_summary": {"part_estimates": [
        {"part_number": "P", "quantity": 1, "manufacturing_questions": [q]},
        {"part_number": "P-01", "quantity": 1, "system_cost": {"unit_cost_gbp": 3.0}},
        {"part_number": "P-02", "quantity": 1, "system_cost": {"unit_cost_gbp": 4.0}}]}}
    ds = [x for x in cf.costed_job(src)["decisions_required"] if x.get("issue") == q["issue"]]
    assert len(ds) == 1 and ds[0]["kind"] == "manufacturing_decision"


# ── 5. the title block names the whole drawing number ────────────────────────────────────

def test_a_four_segment_drawing_number_and_a_hand_are_read_whole():
    assert df._RE_DWGNO.findall("12173-07-2-01M 1:4 A") == ["12173-07-2-01M"]
    assert df._RE_DWGNO.findall("12173-04-02M-H") == ["12173-04-02M-H"]
    assert df._RE_DWGNO.findall("12173-07-1-02M-H") == ["12173-07-1-02M-H"]
    assert df._RE_DWGNO.findall("12349-02-69-01A") == ["12349-02-69-01A"]
    assert df._RE_DWGNO.findall("12173-03-201") == ["12173-03-201"]


class _Page:
    width, height = 1000.0, 700.0

    def __init__(self, words, finish=""):
        self._w = words
        self.finish = finish
        self.lines, self.curves = [], []

    def extract_words(self):
        return self._w

    def extract_text(self):
        return " ".join(w["text"] for w in self._w)


def test_the_title_block_names_the_members_sheet():
    pg = _Page([{"text": "12173-07-2-01M", "top": 690.0, "x0": 900.0}])
    assert df._title_block_part(pg, "") == "12173-07-2-01M"


def test_one_pages_finish_does_not_speak_for_a_pooled_slot(monkeypatch):
    pages = [_Page([{"text": "9999-07-2-GA", "top": 690.0, "x0": 900.0}], "POWDER COATED"),
             _Page([{"text": "9999-07-2-GA", "top": 690.0, "x0": 900.0}], "RAW"),
             _Page([{"text": "9999-07-2-01M", "top": 690.0, "x0": 900.0}], "RAW")]

    class _Pdf:
        def __init__(self, *_a, **_k):
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=_Pdf))
    monkeypatch.setattr(df, "_title_block_fields", lambda page: {"finish": page.finish})
    got = ws.sheet_weld_facts(["fake.pdf"])
    assert got["9999-07-2-GA"]["finish"] == "" and got["9999-07-2-GA"]["finishes"] == [
        "POWDER COATED", "RAW"]
    assert got["9999-07-2-01M"]["finish"] == "RAW"


# ── 6. the specification legend says how, not that ───────────────────────────────────────

_LEGEND = ("WELD SPECIFICATION: • ALL WELDS TO BE TIG UNLESS STATED • RESISTANCE WELDING WIRE "
           "TO WIRE THE SET DOWN SHOULD BE 20% UNLESS STATED • ALWAYS REMOVE BURRS")


def test_the_legend_is_stripped_with_or_without_its_heading():
    assert "WELD" not in ep.strip_specification_legend(_LEGEND + " DRAWN IB").upper()
    bare = ep.strip_specification_legend("SIDE PANEL ALL WELDS TO BE TIG UNLESS STATED FINISH: RAW")
    assert "WELD" not in bare.upper() and "FINISH: RAW" in bare
    kept = ep.strip_specification_legend("CORNERS TO BE WELDED " + _LEGEND + " FINISH: WELDED")
    assert "CORNERS TO BE WELDED" in kept and "FINISH: WELDED" in kept


def test_a_sheet_with_only_the_legend_cues_no_weld():
    page = f"SIDE PANEL 1.5mm MATERIAL: MILD STEEL {_LEGEND} FINISH: RAW COLOUR: RAW"
    s = ep.build_textual_manufacturing_summary(page, notes_text=_LEGEND)
    assert "welding" not in s["inferred_operations"] and "dress_welds" not in s["inferred_operations"]
    assert s["feature_cues"]["weld_detected"] is False
    assert not any(f.get("field") == "welding" for f in s["review_flags"])
    assert ep.legend_cues_set_aside(page) == ["welding"]


def test_a_sheets_own_weld_statement_is_kept():
    for own in ("FINISH: WELDED", "WELD AND DRESS ALL CORNERS", "CORNERS TO BE WELDED"):
        s = ep.build_textual_manufacturing_summary(f"FRAME {own} {_LEGEND}")
        assert "welding" in s["inferred_operations"], own
    s = ep.build_textual_manufacturing_summary(f"FRAME WELD AND DRESS ALL CORNERS {_LEGEND}")
    assert "dress_welds" in s["inferred_operations"]


def test_a_route_quoting_only_the_legend_is_an_inference_and_asked():
    from source_connectors import llm_full_job as lj
    parts = [{"part_number": "P-02M"}, {"part_number": "P-03M"}]
    job = {"routes": [{"operation": "welding", "part_numbers": ["P-02M"], "inferred": False,
                       "evidence": "ALL WELDS TO BE TIG UNLESS STATED"},
                      {"operation": "welding", "part_numbers": ["P-03M"], "inferred": False,
                       "evidence": "WELD AND DRESS"}]}
    lj.apply_routes_to_parts(parts, job)
    assert parts[0]["operation_sources"]["welding"] == "inference"
    assert any("cites only the pack's weld specification" in f for f in parts[0]["review_flags"])
    assert parts[1]["operation_sources"]["welding"] == "llm_full_extract"


def test_the_compiler_holds_a_legend_quoted_weld_as_an_inference():
    import route_compiler as rc
    parts = [{"part_number": "A-101", "description": "ASSEMBLY"},
             {"part_number": "A-01M", "description": "PANEL"}]
    extract = {"top_assembly": {"part_number": "A-101"},
               "assemblies": [{"part_number": "A-101", "children": [{"part_number": "A-01M", "qty": 1}]}],
               "routes": [{"operation": "welding", "scope": "part", "part_numbers": ["A-01M"],
                           "inferred": False, "evidence": "ALL WELDS TO BE TIG UNLESS STATED"}]}
    graph = rc.compile_job_route(parts, extract)
    ds = [x if isinstance(x, dict) else x.__dict__ for x in graph.get("decisions") or []]
    w = [x for x in ds if x.get("operation") == "welding" and x.get("target_id") == "A-01M"]
    assert w and w[0]["source"] == "inference" and not w[0].get("evidence")
    assert "weld specification" in str(w[0].get("reason"))
    assert any(i.get("code") == "weld_route_cites_only_the_specification_legend"
               for i in graph.get("issues") or [])


def test_a_wire_routes_weld_is_an_inference_unless_its_sheet_names_one():
    import document_builder as db

    def run(text):
        part = db._empty_part_record(part_number="9999-04-06M", description="RISER")
        part.update({"pages": [1], "page_roles": ["detail"], "materials": ["MILD STEEL WIRE"]})
        summary = {"pages": [{"page_number": 1, "pdfplumber_text": text,
                              "page_role": {"primary_role": "detail"}}]}
        return db._apply_post_build_fixes([part], summary)[0]

    p = run(f"RISER 3.00 DIA x 451.42 FINISH: RAW {_LEGEND} DRAWN IB")
    assert "welding" in p["textual_operations"]
    assert p["operation_sources"]["welding"] == "inference"
    p = run("RISER 3.00 DIA x 451.42 WELD TO MESH FINISH: RAW")
    assert "welding" in p["textual_operations"]
    assert (p.get("operation_sources") or {}).get("welding") != "inference"


def test_a_process_note_fragment_of_the_legend_is_not_re_read_as_a_weld():
    """file_scan re-infers operations from the part's process-note snippets; a snippet is a
    fragment, so the legend's sentence arrives without its heading."""
    import json_normaliser as jn
    assert jn.infer_operations(jn._strip_spec_boilerplate("ALL WELDS TO BE TIG UNLESS STATED")) == []
    assert "welding" in jn.infer_operations(jn._strip_spec_boilerplate("WELD AND DRESS ALL CORNERS"))
    notes = ep.extract_process_notes(_LEGEND)
    assert "welding" not in notes["operations_from_notes"]


def test_the_model_is_asked_about_numbered_pieces_once_it_is_read():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    sw = src.split('"bom": [vars(r) for r in _sw_job.bom],')[1][:1500]
    assert "recheck_dxf_pieces_against_model" in sw


def _jd(target, op):
    import route_compiler as rc
    return types.SimpleNamespace(target_id=target, operation=op, scope="part",
                                 status=rc.REQUIRED, reason="", participants=[],
                                 field_provenance={})


def test_a_joint_each_sheet_draws_is_not_called_a_double_charge():
    import route_compiler as rc
    graph = {"children": {"W-201": {"W-202": 1}},
             "raw": {"W-201": {"weld_symbols": {"fillet": 2}, "weld_symbol_pages": [6]},
                     "W-202": {"weld_symbols": {"fillet": 1}, "weld_symbol_pages": [7]}}}
    asm, kid = _jd("W-201", "welding"), _jd("W-202", "welding")
    issues = rc._flag_possible_joint_double_charge([asm, kid], graph)
    assert not issues and kid.status == rc.REQUIRED
    assert "both sheets draw their own joints" in kid.reason
    assert "Nothing in the pack distinguishes" not in kid.reason


def test_an_undrawn_overlap_says_what_the_reader_found_and_asks():
    import route_compiler as rc
    graph = {"children": {"W-201": {"W-202": 1}},
             "raw": {"W-201": {"weld_symbols": {}, "weld_symbol_pages": [6]},
                     "W-202": {"weld_symbols": {"fillet": 1}, "weld_symbol_pages": [7]}}}
    asm, kid = _jd("W-201", "welding"), _jd("W-202", "welding")
    issues = rc._flag_possible_joint_double_charge([asm, kid], graph)
    assert any(i["code"] == "joining_charged_on_assembly_and_member" for i in issues)
    assert "named no weld symbol on its own sheet (p.6)" in kid.reason
    assert "BOTH ARE CHARGED" in kid.reason
