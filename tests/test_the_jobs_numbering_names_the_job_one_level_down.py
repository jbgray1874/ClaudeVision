"""Harrods 9439-01-04 Table Standing POS Holder, 5 Oct 2026 (D-395). The estimator typed
"9439-01" — the job's numbering — and the portal refused it: "9439-01 does not name any
drawing added here". It had to be "9439-01-04". James Gray: "shouldn't need this."

D-337 made a bare job number ("12173") name the job, resolved to the assembly no other
drawing lists. The job's numbering one level down is the same case: nothing is numbered
"9439-01" alone, and what is numbered under it (9439-01-04-GA and its sheets) is the job.
The rule stays the parts lists' — one assembly under the prefix needs no list to be on top;
two are a choice. A role token after the typed number ("12173-02-GA" after "12173-02") is the
same sheet, which names_the_product already says, not a sheet under it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import product_identity as pi                                          # noqa: E402
import route_compiler as rc                                            # noqa: E402

FILES = [
    "9439-01-04-GA Table Standing POS Holder_REVA.pdf",
    "9439-01-04-01M Base_REVA.pdf",
    "9439-01-04-02M Upright_REVA.pdf",
    "9439-01-04-03A Lens_REVA.pdf",
]


def test_under_the_numbering_means_a_separator_and_more_digits():
    assert pi.is_under_the_numbering("9439-01", "9439-01-04-GA")
    assert pi.is_under_the_numbering("9439-01", "9439-01-04-01M")
    assert pi.is_under_the_numbering("9439", "9439-01-04-GA")
    assert not pi.is_under_the_numbering("9439-01", "9439-010-GA")      # not the same tokens
    assert not pi.is_under_the_numbering("9439-02", "9439-01-04-GA")
    assert not pi.is_under_the_numbering("12173-02", "12173-02-GA")     # the same sheet
    assert not pi.is_under_the_numbering("", "9439-01-04-GA")


def test_a_prefix_is_a_job_reference_only_when_nothing_is_named_exactly():
    numbers = ["9439-01-04-GA", "9439-01-04-01M"]
    assert pi.numbering_prefix("9439-01", numbers) == "9439-01"
    assert pi.numbering_prefix("9439-01-04", numbers) == ""            # names the GA itself
    assert pi.numbering_prefix("9439-02", numbers) == ""
    assert pi.numbering_prefix("9439", numbers) == ""                   # the bare job number's


def test_the_portal_lets_the_jobs_numbering_run_and_names_the_product():
    r = pi.resolve_product("9439-01", FILES)
    assert r["status"] == "job", r
    assert r["match"]["number"] == "9439-01-04-GA"
    assert "not one drawing" in r["message"] and "9439-01-04-GA" in r["message"]
    assert "Type the one that is the product" not in r["message"]


def test_the_full_number_and_the_bare_job_number_still_work():
    assert pi.resolve_product("9439-01-04", FILES)["status"] == "ok"
    r = pi.resolve_product("9439", FILES)
    assert r["status"] == "job" and r["match"]["number"] == "9439-01-04-GA"


def test_another_jobs_numbering_is_still_refused():
    assert pi.resolve_product("9439-02", FILES)["status"] == "none"


def test_two_assemblies_under_the_prefix_are_a_choice_without_the_parts_lists():
    files = FILES + ["9439-01-05-GA Counter POS Holder_REVA.pdf"]
    r = pi.resolve_product("9439-01", files)
    assert r["status"] == "job" and r["match"] is None, r
    assert "9439-01-04-GA" in r["message"] and "9439-01-05-GA" in r["message"]
    # and the parts lists settle it: 04 lists 05
    texts = {"9439-01-04-GA Table Standing POS Holder_REVA.pdf":
             "1 9439-01-05-GA COUNTER HOLDER 1 DRAWING No 9439-01-04-GA",
             "9439-01-05-GA Counter POS Holder_REVA.pdf": "DRAWING No 9439-01-05-GA"}
    r = pi.resolve_product("9439-01", files, texts=texts)
    assert r["status"] == "job" and r["match"]["number"] == "9439-01-04-GA"


def _pack():
    parts = [{"part_number": "9439-01-04-GA", "description": "TABLE STANDING POS HOLDER",
              "quantity": 1, "is_assembly_parent": True, "page_roles": ["assembly"]}]
    parts += [{"part_number": p, "description": p, "quantity": 1, "page_roles": ["detail"]}
              for p in ("9439-01-04-01M", "9439-01-04-02M", "9439-01-04-03A")]
    extract = {"assemblies": [{"part_number": "9439-01-04-GA", "children": [
        {"part_number": "9439-01-04-01M", "qty": 1}, {"part_number": "9439-01-04-02M", "qty": 2},
        {"part_number": "9439-01-04-03A", "qty": 1}]}]}
    return parts, extract


def test_the_run_prices_the_assembly_numbered_under_the_prefix():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="9439-01")
    assert g["product_root"] == "9439-01-04-GA", g["issues"]
    codes = {i.get("code") for i in g["issues"]}
    assert "declared_product_not_resolved" not in codes
    assert "product_is_the_jobs_top_assembly" in codes
    assert g["quantities"]["9439-01-04-02M"] == 2
    parts, extract = _pack()
    by_ga = rc.build_part_graph(parts, extract, declared_product="9439-01-04")
    assert by_ga["product_root"] == "9439-01-04-GA"
