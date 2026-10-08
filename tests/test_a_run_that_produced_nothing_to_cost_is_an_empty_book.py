"""A run that produced nothing to cost is an empty book, and every deliverable says so (D-409).

12675-01, 8 Oct 2026 09:15, the first run after D-406 closed both doors: no part minted and no
labour row written — and the book was not empty. Packaging and delivery were minted for a
product that did not exist (£23.00); the customer's terms ran over them (£25.46 a unit); the
sheet's labour total of exactly zero read back as missing, so the unit cost went out as
"PENDING — NOT TRACEABLE TO A WORKBOOK CELL"; the headline read "Not for release — 3 to
settle" over two decisions about packing nothing; and the design-intent stop reached no page
and no sheet. The scan had said it in a review flag that nothing downstream read.

The stop is now a structured fact on the record, written once and asked everywhere: the
commercial lines, the quote, the workbook banner, the report's headline, tiles, glance,
Decisions table and verdict, the explanation tab, the covering note's DXF sentences.

With it, D-410: the job's own SolidWorks extract was refused as "describes a different job"
because the job number was read off parts that did not exist. The job's own identity counts.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))

import run_stop  # noqa: E402
import commercial_lines as cl  # noqa: E402
import costed_facts as cf  # noqa: E402
import quote_state as qs  # noqa: E402

_spec = importlib.util.spec_from_file_location("jrh", _ROOT / "src" / "job_report_html.py")
jrh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jrh)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " "))


STOP_REASON = ("THIS PACK IS DESIGN-INTENT SHEETS (page(s) 1, 2, 3, 4, 5) AND THIS WAS AN ENGINE "
               "RUN — no parts list and no part drawings, so the drawing readers have nothing to "
               "cost and this book is empty by mode, not by content.")
NEXT = ("The design being priced is taken off from its own SolidWorks assembly or detailed by "
        "Design into a GA with a parts list and part sheets.")


def _stopped_summary() -> dict:
    s = {"job_source_pdfs": [{"name": "12675-01-GA Stacking Block Model_Design Intent.PDF"}],
         "estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": 10}},
         "manufacturing_writeup": {"parts": []}, "cad_inputs": {}}
    run_stop.record(s, "design_intent_pack_on_engine_run", STOP_REASON, next_step=NEXT,
                    pages=["1", "2", "3", "4", "5"])
    return s


# ── the fact itself ─────────────────────────────────────────────────────────────────────

def test_the_stop_is_a_fact_on_the_record_and_reads_back():
    s = _stopped_summary()
    stop = run_stop.nothing_to_cost(s)
    assert stop and stop["kind"] == "design_intent_pack_on_engine_run"
    assert stop["reason"] == STOP_REASON and stop["next_step"] == NEXT
    assert stop["pages"] == ["1", "2", "3", "4", "5"]
    assert "design-intent sheets" in stop["short"]
    assert run_stop.nothing_to_cost({"manufacturing_writeup": {"parts": []}}) is None
    assert run_stop.nothing_to_cost(None) is None


def test_an_unknown_kind_still_stops_the_book_and_is_printed_not_dropped():
    s = {}
    run_stop.record(s, "something_the_scan_learned", "why it stopped")
    stop = run_stop.nothing_to_cost(s)
    assert stop and stop["short"] == "something the scan learned"
    assert "something the scan learned" in run_stop.sentence(stop)


def test_the_banner_and_the_sentence_are_one_wording():
    stop = run_stop.nothing_to_cost(_stopped_summary())
    sent = run_stop.sentence(stop)
    assert sent.startswith("No price — nothing to cost: the pack is design-intent sheets")
    assert sent.endswith(NEXT)
    ban = run_stop.banner(stop)
    assert ban.startswith("NO PRICE — nothing to cost:") and ban.endswith(NEXT)
    assert not ban.startswith("PROVISIONAL"), "PROVISIONAL promises a figure to finish"


# ── nothing to pack, no packaging ───────────────────────────────────────────────────────

def test_a_stopped_run_ships_nothing():
    why = cl.nothing_to_ship(_stopped_summary(), [{"part_number": "X", "blank_length_mm": 100}])
    assert why and "nothing to cost" in why


def test_a_book_of_placeholders_alone_ships_nothing():
    parts = [{"part_number": "PACKAGING", "_commercial_placeholder": True},
             {"part_number": "POWDER", "source": "commercial_placeholder"},
             {"part_number": "PLATING", "_plating_placeholder": True}]
    assert cl.nothing_to_ship({}, parts) == "no part on this book to pack or deliver"


def test_a_real_part_ships_and_the_lines_are_minted_as_before():
    assert cl.nothing_to_ship({}, [{"part_number": "12696-01-01M", "blank_length_mm": 102.7}]) is None
    assert cl.nothing_to_ship(None, [{"part_number": "A"}]) is None


def test_the_estimator_asks_the_gate_before_minting_packaging_and_delivery():
    """Wired, not only written: the loop over the two codes is empty when nothing ships."""
    src = (_ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "_cl_gate.nothing_to_ship(summary, parts)" in src
    assert "for _code, _desc in (() if _nothing_to_ship else (" in src


# ── a total of exactly zero is a total, in BOTH readers ────────────────────────────────

class _Cell:
    def __init__(self, v):
        self.Value = v


class _Sheet:
    """Enough of an Excel COM worksheet for the label scan: Cells(r, c).Value."""
    def __init__(self, cells):
        self._c = cells

    def Cells(self, r, c):                                           # noqa: N802
        return _Cell(self._c.get((r, c)))


def test_a_labour_total_of_zero_reads_back_as_zero_not_as_missing():
    import wep_readback_from_xlsx as rb
    ws = _Sheet({(223, 3): "Total Labour Cost (Including  Downtime)", (223, 13): 0.0,
                 (147, 3): "Total Material Cost", (147, 13): 23.0,
                 (225, 11): "Total Unit Cost Price", (225, 13): 25.46})
    assert rb._scan_total(ws, ("total labour cost",), 240, 16) == 0.0
    assert rb._scan_total(ws, ("total material cost",), 240, 16) == 23.0
    assert rb._scan_total(ws, ("total unit cost",), 240, 16) == 25.46
    assert rb._scan_total(ws, ("sell price",), 240, 16) is None, "a label absent is still None"


def test_the_two_total_readers_are_one_reader():
    import wep_readback_from_xlsx as rb
    assert "_scan_total_cell(com_ws, label_needles" in inspect.getsource(rb._scan_total)


# ── the one record: first row, first reason, the tally ──────────────────────────────────

def test_the_record_carries_the_stop_as_its_first_row_and_first_reason():
    rec = cf.costed_job(_stopped_summary())
    decs = rec["decisions_required"]
    assert decs and decs[0]["kind"] == "nothing_to_cost"
    assert decs[0]["issue"].startswith("Nothing to cost:")
    assert decs[0]["action"] == NEXT
    assert rec["release"]["draft"] is True
    assert rec["release"]["status"] == "provisional"
    assert rec["release"]["reasons"][0] == run_stop.sentence(rec["run_stop"])
    assert rec["run_stop"]["kind"] == "design_intent_pack_on_engine_run"


def test_the_tally_names_the_stop_first_and_counts_it_once():
    rec = cf.costed_job(_stopped_summary())
    o = cf.outstanding_summary(rec)
    assert o["phrase"].startswith("nothing to cost — the run stopped before pricing")
    assert o["nothing_to_cost"] == 1
    assert o["total"] == len(rec["decisions_required"])
    assert o["other"] == 0, "the stop lands in its own bucket, not in 'other open items'"


def test_a_record_without_a_stop_is_unchanged():
    rec = cf.costed_job({"manufacturing_writeup": {"parts": []},
                         "estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": 1}}})
    assert rec["run_stop"] is None
    assert all(d["kind"] != "nothing_to_cost" for d in rec["decisions_required"])


# ── the covering note's DXF sentences read the reason, not the list ─────────────────────

def test_a_refused_drawing_export_is_not_called_a_stray_file():
    s = {"dxf_augmentation": {"unmatched_dxf": [
        {"path": r"C:\stage\12675-01-02 Block Model V2.dxf", "part_number": "12675-01-02",
         "reason": ("drawing_export_not_a_flat: 22 dimension entities — this is a drawing of "
                    "the part, not its flat pattern")},
        {"path": r"C:\stage\12675-03-BLACK.DXF", "part_number": "12675-03",
         "reason": "code_belongs_to_another_assembly_in_this_job_number"},
        {"path": r"C:\stage\odd.DXF", "reason": "no_part_number_in_filename"}]}}
    out = cf.pack_shortfalls(s)
    joined = " | ".join(out)
    assert ("'12675-01-02 Block Model V2.dxf' is a drawing export, not a manufacturing flat "
            "(22 dimension entities)") in joined
    assert "never a part" in joined
    assert "Block Model V2.dxf' matched no part" not in joined
    assert "'12675-03-BLACK.DXF' matched no part in this job — its code belongs to another assembly" in joined
    assert "'odd.DXF' carries no part number in its name" in joined


def test_the_dxf_vocabulary_has_one_home():
    assert jrh._DXF_REASON_SENTENCES is cf.DXF_REASON_SENTENCES
    assert jrh._dxf_record_reason is cf.dxf_record_reason
    assert cf.dxf_record_names({"dxf": r"C:\a\b\X.DXF"}) == ["X.DXF"]
    assert cf.dxf_record_names({"candidates": [r"C:\a\1.DXF", "/mnt/a/2.DXF"]}) == ["1.DXF", "2.DXF"]


# ── the quote: no price, said in the price's own words ──────────────────────────────────

def test_the_price_fact_is_no_price_not_an_indicative_figure():
    s = _stopped_summary()
    s["estimate_summary"]["workbook_equivalent_pricing"] = {"m105_total_unit_cost_gbp": 25.46}
    s["final_estimate"] = {"totals": {"unit_gbp": 25.46, "unit_cell": "Estimate!M225",
                                      "unit_cell_value": 25.46}}
    price = qs._price_fact(s)
    assert price["amount"] is None and price["workbook_amount"] is None
    assert price["nothing_to_cost"] is True
    assert price["why"].startswith("No price — nothing to cost:")


def test_the_quote_state_names_the_stop_as_its_first_gate():
    st = qs.quote_state(_stopped_summary())
    assert st["customer_releasable"] is False
    assert st["blocking"][0]["gate"] == "nothing_to_cost"
    assert "nothing to cost" in st["blocking"][0]["short"]
    assert all(b["gate"] != "traceable_price" for b in st["blocking"]), \
        "there is no price to trace, so 'untraceable' is the wrong word"


def test_the_quote_page_prints_the_stop_not_enter_the_unit_cost():
    src = (_ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert '_state["price"].get("nothing_to_cost")' in src


# ── the report: one answer on every surface ─────────────────────────────────────────────

def test_the_unit_text_is_no_price_wherever_it_is_printed():
    hl = jrh._extract_headline(_stopped_summary())
    assert hl["nothing_to_cost"]
    assert jrh._unit_text(hl) == run_stop.HEADLINE
    assert "PENDING" not in jrh._unit_text(hl)


def test_the_release_words_are_the_stop():
    s = _stopped_summary()
    rec = cf.costed_job(s)
    cls, head, reasons = jrh._release_words(rec, s)
    assert cls == "t-bad" and head == "No price — this run produced nothing to cost"
    assert reasons[0] == run_stop.sentence(rec["run_stop"])


def test_the_whole_report_says_no_price_first_and_nowhere_says_pending():
    html = jrh.build_report_html(_stopped_summary())
    text = _text(re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    assert run_stop.HEADLINE in text
    assert html.index(run_stop.HEADLINE) < html.index("<h2>Summary</h2>"), "the stop is read first"
    assert "design-intent sheets" in text
    assert "Nothing to cost" in text                       # the Decisions table's row
    assert "PENDING — NOT TRACEABLE" not in text
    assert "Not for release — " not in text
    assert "No price was produced on this run" in text    # the verdict
    # the glance shows no labour figure to contradict the sheet
    glance = text[text.index("Estimate at a glance"):text.index("Estimate at a glance") + 600]
    assert "Labour" not in glance.replace("labour figure", "")


def test_a_report_without_a_stop_has_no_stop_callout():
    s = {"job_source_pdfs": [{"name": "ga.pdf"}], "cad_inputs": {},
         "estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": 1}}}
    assert jrh._render_run_stop(s) == ""
    assert run_stop.HEADLINE not in jrh.build_report_html(s)


# ── the sheet: the banner beside the price cells ────────────────────────────────────────

def test_the_sheet_carries_the_stop_beside_every_price_cell_and_no_provisional_banner():
    openpyxl = pytest.importorskip("openpyxl")
    import wb_populate as wp
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["F6"] = "Unit Cost"; ws["G6"] = "=M225"
    ws["K225"] = "Total Unit Cost Price"; ws["M225"] = "=((M147+M223)/(100%-M227))/0.92"
    ws["K231"] = "Sell Price"; ws["M231"] = "=M225/(100%-M229)"
    flags: list = []
    assert wp._write_run_stop_banner(ws, _stopped_summary(), flags) is True
    banners = [c.value for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and c.value.startswith("NO PRICE — ")]
    assert len(banners) == 3, banners
    assert all("design-intent sheets" in b for b in banners)
    assert any(f.startswith("NO PRICE:") for f in flags)
    # the estimator-inputs banner stands aside, the checklist anchor row is still found
    before = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert wp._write_beside_price_labels(ws, None) == 231
    after = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert before == after, "a None text writes nothing"
    assert all(not (isinstance(v, str) and v.startswith("PROVISIONAL")) for v in after)


def test_a_sheet_with_no_stop_gets_no_stop_banner():
    openpyxl = pytest.importorskip("openpyxl")
    import wb_populate as wp
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["F6"] = "Unit Cost"; ws["G6"] = 12.0
    flags: list = []
    assert wp._write_run_stop_banner(ws, {"manufacturing_writeup": {"parts": []}}, flags) is False
    assert ws["H6"].value is None and not flags


# ── the explanation tab, the product sentence ───────────────────────────────────────────

def test_the_explanation_tab_answers_the_first_question_with_the_stop():
    src = (_ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    assert "What does a unit cost, and of what?** {_stop_sentence(_stop)}" in src


def test_a_root_with_no_number_is_said_not_printed_as_brackets():
    src = (_ROOT / "src" / "route_compiler.py").read_text(encoding="utf-8")
    assert "that carries no drawing number of its own" in src
    assert "The pack has one top-level assembly ({', '.join(top_ids)})" not in src


# ── D-410: the job's own extract is the job's, parts or no parts ────────────────────────

def _extract(top: str, *codes: str):
    from source_connectors import solidworks as sw
    return sw.NativeJob(part_signals={c: sw.NativePart(part_number=c) for c in codes},
                        assembly_pns=[top], meta={"top_assembly": top}, found=True)


def test_a_pack_with_no_parts_still_knows_whose_extract_it_is():
    from source_connectors import solidworks as sw
    job = _extract("12675-01-02 Block Model V2", "12675-01-02 BM V2 MDF Base",
                   "12675-01-02 BM V2 Stainless")
    before = sw.extract_is_for_this_job([], job)
    assert before["belongs"] is False and before["shares_job_number"] is False, \
        "read off the parts alone, an empty pack has no job number at all"
    after = sw.extract_is_for_this_job([], job, job_identity=["12675-01", None, "12675-01"])
    assert after["belongs"] is False, "the guard is unchanged: zero matches, nothing applied"
    assert after["shares_job_number"] is True
    assert after["job_has_no_parts"] is True and after["job_parts"] == 0


def test_a_foreign_extract_is_still_foreign_with_the_identity_given():
    from source_connectors import solidworks as sw
    job = _extract("12120-01-GA", "12120-01-01", "12120-01-02")
    res = sw.extract_is_for_this_job([{"part_number": "2085-02"}], job,
                                     job_identity=["2085-02", "2085-02"])
    assert res["belongs"] is False and res["shares_job_number"] is False
    assert res["job_has_no_parts"] is False


def test_the_refusal_names_the_third_failure_not_a_naming_convention():
    import invariants as inv

    def _msg(sw_block):
        vs = inv.check_native_evidence_is_current({"solidworks_native": sw_block})
        return " ".join(str(v.get("message") or "") for v in vs
                        if str(v.get("code") or v.get("check") or "") == "native_extract_refused")

    base = {"refused_wrong_job": True, "extract_path": "x",
            "extract_top_assembly": "12675-01-02 Block Model V2"}
    own_empty = _msg({**base, "refused_own_job": True, "job_has_no_parts": True})
    assert "the pack produced no part records to match it against" in own_empty
    assert "the model is the parts list where the pack has none" in own_empty
    assert "naming convention" not in own_empty
    own_named = _msg({**base, "refused_own_job": True, "job_has_no_parts": False})
    assert "a naming convention it does not know" in own_named
    foreign = _msg({**base, "refused_own_job": False, "job_has_no_parts": True})
    assert "describes a different job" in foreign


def test_the_scan_hands_the_jobs_identity_to_the_guard():
    src = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert 'job_identity=[summary.get("drawing_number"), summary.get("job_name")' in src
    assert "the pack produced NO part records to match it" in src
    assert '"job_has_no_parts": _empty_job,' in src


# ── D-413: an empty book says why BOTH doors gave nothing ───────────────────────────────

def test_the_page_prints_why_the_model_and_the_concept_read_both_gave_nothing():
    s = _stopped_summary()
    run_stop.record(
        s, "design_intent_pack_on_engine_run", STOP_REASON, next_step=NEXT, pages=["1", "2"],
        model_takeoff=("2 designs in the model under the number this run was given (12675-01) and "
                       "nothing says which to price: 12675-01-Block Model, 12675-01-02 Block Model V2"),
        concept_read="the pack contains 12675-01-02 Block Model V2.dxf — measured CAD is never sighted over")
    stop = run_stop.nothing_to_cost(s)
    why = run_stop.doors(stop)
    assert why.startswith("the model take-off did not run: 2 designs in the model")
    assert "the concept read did not run: the pack contains 12675-01-02 Block Model V2.dxf" in why
    html_out = jrh._render_run_stop(s)
    assert "Why both doors gave nothing" in html_out
    assert "12675-01-Block Model, 12675-01-02 Block Model V2" in html_out
    assert "measured CAD is never sighted over" in html_out
    rec = cf.costed_job(s)
    assert rec["decisions_required"][0]["kind"] == "nothing_to_cost"
    assert "the model take-off did not run" in rec["decisions_required"][0]["assumption"]


def test_a_stop_with_no_door_reasons_prints_none_and_invents_none():
    s = _stopped_summary()
    assert run_stop.doors(run_stop.nothing_to_cost(s)) == ""
    assert "Why both doors" not in jrh._render_run_stop(s)


def test_the_scan_records_both_doors_on_the_deferred_stop():
    src = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_di_pending = (_di_stop, _di_next, _di_why)" in src
    assert 'model_takeoff=str(_di_pending[2] or "")' in src
    assert 'or "the concept read produced no part"' in src
