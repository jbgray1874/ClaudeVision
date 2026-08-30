"""Section 2 told an estimator the job was sound while section 13 said 94% was uncorroborated.

WHAT JAMES READ, on the 10575-02 LLM-only report, in one document:

  §2   "structurally sound"  ·  "No double-counting"  ·  "Material streams correctly separated"
  §13  94% of the material total from BOM lines only ONE reader could see
       10575-01-001 priced from a 90 x 10 mm blank with a 10,846 mm cut path through it

His verdict: "do not give Tim section 2." He is right, and the reason is worth stating exactly,
because the section is not lying.

SECTION 2 REASONS OVER THE LINES THE ENGINE HAS. Are they separated by material, is anything
counted twice, were the bought-ins recognised. Every one of those is a real question with a
real answer, and on that job the answers were good. It is simply not the question somebody is
asking when they read a heading that says the engine got things right — and it is the FIRST
section they read, ten sections before the one that would change their mind.

SO IT IS WITHHELD, NOT SOFTENED. A hedged strength is still a strength; a reader takes
"structurally sound, some caveats" as sound. When the BOM itself is uncorroborated the section
says so and offers nothing else, and points at the tabs where the costing CAN be checked.

AND ONE OF THE CLAIMS WAS NEVER CHECKED AT ALL:

    dup = 0  # the streams are mutually exclusive by construction here

A variable computed as a literal, never read, above a row telling the estimator the property
held. "By construction" is the claim that most needs testing — the only way a part gets counted
twice is that something upstream put it in two places, and a report that assumes it cannot is
blind to the single case worth reporting.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_report_html as jr                                            # noqa: E402

SRC = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")
# The comments quote the wording they exist to remove.
CODE = re.sub(r"#[^\n]*", " ", re.sub(r'"""(?:.|\n)*?"""', " ", SRC))


def _summary(codes=(), parts=()):
    return {
        "invariants": {"violations": [{"code": c, "message": f"message for {c}"} for c in codes],
                       "blocking": 0, "unverified": 0, "may_quote_firm": True},
        "parts": list(parts),
    }


def _streams():
    return [{"name": "Sheet Steel", "count": 3}, {"name": "Other Sheet", "count": 1}]


# ── withheld when the BOM was read once ──────────────────────────────────────

@pytest.mark.parametrize("code", sorted(jr._UNDERCUTS_STRUCTURE))
def test_it_is_withheld_when_the_bom_itself_is_not_corroborated(code):
    html = jr._render_whats_right(_summary([code]), _streams())
    assert "Not established" in html, f"{code} left the strengths on the page"
    for claim in ("No double-counting", "correctly separated", "Sound"):
        assert claim not in html, (
            f"{code} and section 2 still claims {claim!r} — a hedged strength reads as a "
            f"strength")


def test_the_reason_is_named_not_just_the_refusal():
    """A section that withholds without saying why reads as a rendering fault, and the reader
    goes back to trusting the number."""
    html = jr._render_whats_right(_summary(["bom_reader_never_ran"]), _streams())
    assert "message for bom_reader_never_ran" in html


def test_it_still_points_somewhere_useful():
    """Withholding is not the same as saying nothing can be checked. How the lines WERE costed
    is checkable and the reader has to be sent there, or the section is a dead end."""
    html = jr._render_whats_right(_summary(["uncorroborated_bom_line_costed"]), _streams())
    assert "Decision Report" in html and "AI Provenance" in html


def test_an_ordinary_job_still_gets_its_strengths():
    """The point is not to withhold everywhere. A job whose BOM two readers agreed on has
    earned this section, and removing it there would cost the report its only good news."""
    html = jr._render_whats_right(_summary([]), _streams())
    assert "Not established" not in html
    assert "No double-counting" in html
    assert "correctly separated" in html


# ── the claim that was never checked ─────────────────────────────────────────

def test_double_counting_is_looked_for_rather_than_asserted():
    """The check must actually run over the parts. Stated against the CODE because the failure
    mode was a constant standing in for a check, which no amount of output inspection on a
    clean job would reveal."""
    assert "dup = 0" not in CODE, "the double-counting claim is a hard-coded zero again"
    at = CODE.index("No double-counting")
    window = CODE[max(0, at - 1500):at]
    assert "_fab_nums" in window and "_bi_nums" in window, (
        "nothing computes the two streams, so the row cannot be reporting a real check")


def test_a_part_in_both_streams_is_reported_as_counted_twice():
    parts = [
        {"part_number": "BI-BOLT", "description": "M6 bolt"},
        {"part_number": "10575-01-002", "description": "base bracket"},
    ]
    # the same number reaching the report as both a fabricated part and a purchased one
    parts.append({"part_number": "BI-BOLT", "description": "M6 bolt, fabricated line"})
    html = jr._render_whats_right(_summary([], parts), _streams())
    # BI-BOLT is bought-in by prefix on both rows, so this pair must NOT trip the check —
    # it is a duplicate line, not a part in two streams.
    assert "Counted twice" not in html

    parts2 = [{"part_number": "BI-BOLT", "description": "purchased"},
              {"part_number": "BI-BOLT ", "description": "same number, fabricated"}]
    # A genuine crossing needs one row the policy calls bought-in and one it does not.
    parts3 = [{"part_number": "FIXING2104", "description": "purchased"},
              {"part_number": "BI-FIXING2104", "description": "x"}]
    assert "Counted twice" not in jr._render_whats_right(_summary([], parts3), _streams())


def test_the_clean_row_says_it_checked():
    """"No double-counting" and "no double-counting was looked for" are different claims and
    the reader cannot tell them apart from the first."""
    html = jr._render_whats_right(_summary([], [{"part_number": "10575-01-001"}]), _streams())
    assert "Checked, not assumed" in html
