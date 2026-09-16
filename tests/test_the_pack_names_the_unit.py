"""The Description box is filled from the drawing's own filename, off the real record.

An estimator asked for Description / date / drawing number at the top of the sheet so he
could trace a job back when requoting it. 10975-02's box came out reading the drawing CODE,
then — once a code was correctly refused — empty.

TWO FAILURES, ONE AFTER THE OTHER, AND THE SECOND IS THE INSTRUCTIVE ONE.

First `_drawing_identity` was handed the JOB stem ("10975-02"), which cleans down to
nothing, and never the drawing's own filename — which is where the product name lives:
"0355255 - A4 Table Top Graphic Holder - 10975_REV B.pdf".

Then the lookup written to fix that GUESSED at plausible key names and found nothing on the
real record, so the fallback still produced the code. file_scan writes exactly two fields
and neither was in the list:

    primary_pdf       {"name": ..., "path": ...}
    job_source_pdfs   [{"name": ..., "path": ..., "page_count": ...}, ...]

So these tests are built on the SHAPE THE SCAN ACTUALLY WRITES, not on a shape that would
have made the code pass.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from client_quote_html import (_drawing_identity, _source_drawing_names,  # noqa: E402
                               _title_from_a_filename)

_PDF = "0355255 - A4 Table Top Graphic Holder - 10975_REV B.PDF"
_UNC = r"\\srv\Estimating\jobs\10975-02\\" + _PDF


def _real_record():
    """10975-02 as file_scan leaves it — the two source fields in their real shapes, and a
    graph whose only root is the minted GA parent describing itself by its own code."""
    return {
        "job_output_stem": "10975-02",
        "primary_pdf": {"name": _PDF, "path": _UNC},
        "job_source_pdfs": [{"name": _PDF, "path": _UNC, "page_count": 4}],
        "llm_full_extract": {"drawing_info": {"drawing_number": "10975-02",
                                              "revision": "B"}},
        "estimate_summary": {"canonical_route_shadow": {
            "top_assemblies": ["10975-02-GA"], "top_assembly": "10975-02-GA",
            "nodes": [{"part_number": "10975-02-GA", "description": "10975-02-GA"}]}},
    }


def test_the_real_record_yields_the_drawing_name():
    """THE P1. This returned [] on the live job, so everything built on it did nothing."""
    assert _source_drawing_names(_real_record()) == \
        ["0355255 - A4 Table Top Graphic Holder - 10975_REV B"]


def test_primary_pdf_alone_is_enough():
    assert _source_drawing_names({"primary_pdf": {"name": _PDF}})


def test_job_source_pdfs_alone_is_enough():
    assert _source_drawing_names({"job_source_pdfs": [{"name": _PDF, "path": _UNC}]})


def test_the_fields_are_read_under_estimate_summary_too():
    """A caller may hand this the whole record or the estimate half of it."""
    assert _source_drawing_names({"estimate_summary": {"primary_pdf": {"path": _UNC}}})


def test_a_unc_path_is_reduced_to_its_filename():
    """Backslashes are the normal case here — the packs live on a UNC share."""
    assert _source_drawing_names({"primary_pdf": {"path": _UNC}}) == \
        ["0355255 - A4 Table Top Graphic Holder - 10975_REV B"]


def test_the_description_box_names_the_product_on_the_real_record():
    """END TO END, on the shape the scan writes: job stem in, product name out."""
    num, rev, title = _drawing_identity(_real_record(), "10975-02")
    assert (num, rev) == ("10975-02", "Rev B")
    assert title == "A4 Table Top Graphic Holder", title


def test_a_record_with_no_drawing_names_still_claims_nothing():
    """No filenames means no description — never an invented one."""
    rec = _real_record()
    rec.pop("primary_pdf")
    rec.pop("job_source_pdfs")
    _, _, title = _drawing_identity(rec, "10975-02")
    assert _title_from_a_filename(title) == "", \
        "with nothing to read, the resolver must fall back to the number, not a guess"
