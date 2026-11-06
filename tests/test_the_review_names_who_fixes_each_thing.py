"""One bucket held three people's work, and an estimator could hand none of it on.

"MISSING OR BROKEN INPUTS" CARRIED, ON ONE JOB: a flat pattern nobody has drawn, a rate nobody
has entered in SDILive, and a node the engine invented. Filed together because none of them is
estimating — which is true and useless. They are fixed by the drawing office, by whoever
maintains the price data, and by us, and a reader given one list cannot pass any of it along.

WHAT JAMES ASKED FOR, after reading the 10575-02 pack end to end: "we should highlight missing
drawings, and unclear geometry, issues with drawings... it should be more a case of highlighting
issues with missing prices in SDILive, poor drawings etc." And, of the alarm layer: "they
already know they need to check everything."

So the split is by WHO FIXES IT, and nothing in it is a verdict on the total. The codes were
already sorted this way in engine_discoveries — _NOT_OURS had "Commerce:" and "The drawing pack"
as comments over two halves of one set — the classifier just collapsed both to "drawing".

THE ORDER IS TIME, NOT SEVERITY. A flat pattern has to be asked for and waited on, so it goes
first and goes early enough to be worth asking. A rate is a row somebody can add today. The
confirms need the job open and nothing else. Ours is last because it is our morning's work.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import engine_discoveries as ed                                        # noqa: E402
import estimating_review as er                                         # noqa: E402


# Every code that fired on 10575-02, with who it belongs to.
JOB = {
    "cad_files_not_read":                      er.DRAWINGS,
    "blank_and_cut_path_disagree":             er.DRAWINGS,
    "no_part_dxf":                             er.DRAWINGS,
    "detail_drawing_missing":                  er.DRAWINGS,
    "material_has_no_rate_in_this_engine":     er.PRICES,
    "stated_finish_not_costed":                er.PRICES,
    "price_not_reproducible":                  er.PRICES,
    "bought_in_without_a_catalogue_price":     er.PRICES,
    "two_sources_disagree_about_the_material": er.CONFIRM,
    "short_run_pays_for_sheet_it_does_not_use": er.CONFIRM,
    "bom_node_disconnected":                   er.BROKEN,
    "throughput_size_banded":                  er.INFORMATION,
}


@pytest.mark.parametrize("code,bucket", sorted(JOB.items()))
def test_each_finding_reaches_the_person_who_can_fix_it(code, bucket):
    rev = er.review({"violations": [{"code": code, "message": "x"}]})
    titles = [g["title"] for g in rev["buckets"]]
    assert titles == [bucket], f"{code} filed under {titles} instead of {bucket!r}"


def test_a_missing_drawing_and_a_missing_rate_are_never_in_the_same_list():
    """THE DEFECT, STATED. One is a phone call to the drawing office and one is a row in a
    database; nothing an estimator does resolves either, and lumping them wastes both."""
    rev = er.review({"violations": [
        {"code": "cad_files_not_read", "message": "no flat pattern"},
        {"code": "material_has_no_rate_in_this_engine", "message": "no rate for PETG"},
    ]})
    by = {g["title"]: {l["code"] for l in g["lines"]} for g in rev["buckets"]}
    assert by[er.DRAWINGS] == {"cad_files_not_read"}
    assert by[er.PRICES] == {"material_has_no_rate_in_this_engine"}


def test_the_drawing_office_is_asked_first_because_waiting_takes_longest():
    assert er.ORDER[0] == er.DRAWINGS
    assert er.ORDER.index(er.PRICES) < er.ORDER.index(er.CONFIRM)


def test_every_bucket_says_what_to_do_about_it():
    """A heading with no instruction is a heading somebody has to interpret, and the fourth
    job is where they stop."""
    for title in er.ORDER:
        assert er._BUCKET_ACTION.get(title), f"{title!r} has no default action"


@pytest.mark.parametrize("bucket,words", [
    (er.DRAWINGS, "drawing office"),
    (er.PRICES, "SDILive"),
])
def test_the_default_action_names_the_owner(bucket, words):
    assert words.lower() in er._BUCKET_ACTION[bucket].lower()


def test_no_bucket_tells_the_estimator_not_to_quote():
    """"They already know they need to check everything." The value is the finding and the
    lever; a verdict on the total is the engine taking a decision that was never its to make —
    which estimating_review's own docstring already argued, and which the buckets must not
    reintroduce through their headings."""
    for title in er.ORDER:
        text = (title + " " + er._BUCKET_ACTION[title]).upper()
        for banned in ("DO NOT QUOTE", "NOT A FIRM PRICE", "INSUFFICIENT DATA", "BLOCKING"):
            assert banned not in text, f"{title!r} passes a verdict: {banned}"


# ── the metric must not shrink because the classes grew ──────────────────────

def test_splitting_the_classes_did_not_shrink_the_score():
    """"Not ours" is one number and has to stay one number. Counting only the drawing third
    would have reported two where there were eight, which reads as six problems solved by a
    refactor."""
    codes = [c for c, b in JOB.items() if b in (er.DRAWINGS, er.PRICES, er.CONFIRM)]
    c = ed.count([{"code": x} for x in codes])
    assert c["drawing_and_commercial"] == len(codes), c["drawing_codes"]


def test_the_three_are_also_available_apart():
    """The rolled-up number is the score; these are the work, and a report that wants to say
    who should not have to re-derive it."""
    c = ed.count([{"code": "cad_files_not_read"},
                  {"code": "material_has_no_rate_in_this_engine"},
                  {"code": "two_sources_disagree_about_the_material"}])
    assert c["drawing_office"] == ["cad_files_not_read"]
    assert c["sdilive"] == ["material_has_no_rate_in_this_engine"]
    assert c["estimator"] == ["two_sources_disagree_about_the_material"]


def test_an_unclassified_code_is_still_counted_as_ours():
    """The pressure that keeps the table honest: a new check nobody classified inflates the
    number it would otherwise vanish from."""
    assert ed.classify("something_nobody_has_filed_yet") == "engine"
