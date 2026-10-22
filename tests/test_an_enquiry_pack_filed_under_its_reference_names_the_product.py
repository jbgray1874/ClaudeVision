"""An enquiry pack filed under the customer's reference, its title, then the customer's own
drawing number names the product by either number (D-583).

M&S 0351292, 22 Oct 2026: the pack arrived as one PDF, "0351292-UNIVERSAL MIDFLOOR 1200
RAIL-ROL2021-2465-00.pdf", and the portal refused every Drawing Number typed — the whole
name, the UPC 0351292 and the drawing's own ROL2021-2465-00 — with "does not name any
drawing added here". Read number-first, the file was a drawing numbered "0351292-UNIVERSAL";
and ROL's numbering opens with letters, which the engine's drawing-number shape (a leading run
of digits) does not admit. The file-name reader now reads the customer's filing: reference,
title, drawing number; the reference names the pack as a job number does; the shape is widened
in that one place only."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import product_identity as pi  # noqa: E402

PACK = "0351292-UNIVERSAL MIDFLOOR 1200 RAIL-ROL2021-2465-00.pdf"


def test_the_filing_is_read_as_reference_title_and_drawing_number():
    d = pi.drawing_of_file(PACK)
    assert d["number"] == "ROL2021-2465-00"
    assert d["title"] == "UNIVERSAL MIDFLOOR 1200 RAIL"
    assert d["reference"] == "0351292"
    assert d["top_sheet"] and d["is_assembly"]


def test_the_reference_and_the_drawing_number_both_name_the_product():
    for typed in ("0351292", "ROL2021-2465-00"):
        r = pi.resolve_product(typed, [PACK])
        assert r["status"] == "ok", r
        assert r["match"]["number"] == "ROL2021-2465-00"
    assert pi.title_from_files("0351292", [PACK]) == "UNIVERSAL MIDFLOOR 1200 RAIL"
    assert pi.title_from_files("ROL2021-2465-00", [PACK]) == "UNIVERSAL MIDFLOOR 1200 RAIL"


def test_another_reference_names_nothing_and_the_page_says_what_is_here():
    r = pi.resolve_product("0351293", [PACK])
    assert r["status"] == "none"
    assert "ROL2021-2465-00" in r["message"]


def test_the_shape_is_widened_only_in_the_file_name():
    """ROL's numbering is accepted after a reference and a title; the engine's own shape test,
    which every BOM reader relies on, is not changed here."""
    assert not pi.looks_like_a_drawing_number("ROL2021-2465-00")
    assert pi.customer_filing("0351292-UNIVERSAL MIDFLOOR 1200 RAIL-ROL2021-2465-00")["number"] == "ROL2021-2465-00"
    assert pi.customer_filing("12645-01GA_V2_REVA") == {}
    assert pi.customer_filing("12345-ASSY") == {}            # a role token is not a title


def test_the_earlier_filings_read_as_they_did():
    shelter = pi.drawing_of_file("12645 - DRS External Shelter V2 REVA.PDF")
    assert (shelter["number"], shelter["title"], shelter["top_sheet"]) == ("12645", "DRS External Shelter V2", True)
    assert "reference" not in shelter
    body = pi.drawing_of_file("12645-01GA_V2_REVA.PDF")
    assert body["number"] == "12645-01GA" and body["is_assembly"] and not body["top_sheet"]
    riser = pi.drawing_of_file("0359887_TSE FOOTWEAR RISER_12527-22-GA_REV A.pdf")
    assert (riser["number"], riser["title"]) == ("12527-22-GA", "TSE FOOTWEAR RISER")
    rail = pi.drawing_of_file("401918-01-GA_1200 Rail - Chalk White - RevB 0351031.PDF")
    assert rail["number"] == "401918-01-GA" and rail["revision"] == "B"
    r = pi.resolve_product("12645", ["12645 - DRS External Shelter V2 REVA.PDF",
                                     "12645-01GA_V2_REVA.PDF", "12645-02GA_REVA.pdf"])
    assert r["status"] == "ok" and r["match"]["number"] == "12645" and r["match"]["is_assembly"]


def test_a_seven_digit_reference_is_a_job_number():
    assert pi.job_number_only("0351292") == "0351292"
    assert pi.job_number_only("03512921") == ""
    assert pi.names_the_product("0351292", "0351292 - UNIVERSAL MIDFLOOR 1200 RAIL")
    assert not pi.names_the_product("0351292", "0351292-01-GA")
