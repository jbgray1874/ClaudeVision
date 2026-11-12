"""What does Grok make of this pack by itself? Until now, unanswerable.

The engine reads a pack four ways — a deterministic BOM reader, a vision model, DXF flat
patterns, and the SolidWorks native extract — and the whole design is that they check each
other. Which is right for estimating, and makes one question impossible to ask: what does the
model read UNAIDED? Any attempt to find out has three other readers quietly supplying half the
rows and correcting the other half.

`--llm-only` turns them off. Every page goes to the model, nothing corroborates anything, and
the output is a MEASUREMENT of the model rather than an estimate — the source waterfall ranks
an LLM read last, at 0.68 and capped, for exactly the reasons this run makes visible.

WHY IT IS SAFE. It is composed from switches that already exist and it is purely additive:
SDI_LLM_ONLY skips Path A, SDI_APPLY_SOLIDWORKS=0 and SDI_SW_RUN_ANALYSER=0 stop the native
extract being read or built, auto_discover_dxf goes False. Nothing changes on a normal run.

WHAT THIS FILE GUARDS. A diagnostic that produces a workbook looks exactly like an estimate
that produced a workbook — same flags, same sheets, same totals column. The one outcome that
must never happen is somebody finding that file in six months and taking it for a price. So
the run announces itself, loudly, every time.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
_MAIN = (_ROOT / "src" / "main.py").read_text(encoding="utf-8")
_MERGE = (_ROOT / "src" / "merge_boms.py").read_text(encoding="utf-8")


def _flag_block() -> str:
    at = _MAIN.index('if getattr(args, "llm_only", False):')
    return _MAIN[at:at + 2000]


# ── it turns off every other reader ──────────────────────────────────────────

def test_the_flag_exists_and_is_off_by_default():
    """action="store_true" — a normal run is untouched, which is what makes this safe to
    add to a live engine without a pack to test against."""
    assert '"--llm-only"' in _MAIN
    at = _MAIN.index('"--llm-only"')
    assert 'action="store_true"' in _MAIN[at:at + 200]


@pytest.mark.parametrize("switch,what", [
    ("SDI_LLM_ONLY", "the deterministic BOM reader"),
    ("SDI_APPLY_SOLIDWORKS", "the SolidWorks native extract"),
    ("SDI_SW_RUN_ANALYSER", "building a new SolidWorks extract"),
])
def test_every_other_reader_is_switched_off(switch, what):
    assert switch in _flag_block(), f"--llm-only does not turn off {what}"


def test_the_dxf_flat_patterns_are_off_too():
    """A DXF is a measurement of the real part. Left on, the blanks would be right and the
    run would look far better than the model actually is."""
    assert "auto_discover_dxf = False" in _flag_block()


def test_it_does_not_pay_for_a_solidworks_extract_it_will_not_read():
    """SDI_APPLY_SOLIDWORKS=0 stops it being READ. Without SDI_SW_RUN_ANALYSER=0 the analyser
    still runs — four minutes and a licence seat spent producing a file this run ignores."""
    block = _flag_block()
    assert 'os.environ["SDI_SW_RUN_ANALYSER"] = "0"' in block


# ── the model really is on its own ───────────────────────────────────────────

def test_path_a_is_skipped_and_the_absence_is_recorded():
    """An absent reader leaves no trace in what it did not find. `unread` is how the run says
    which readers could not see a page, and a DISABLED reader has to appear there too —
    otherwise the output is indistinguishable from a pack the deterministic reader found
    nothing in."""
    at = _MERGE.index("if llm_only:")
    body = _MERGE[at:at + 900]
    assert "a_boms" in body and "unread" in body
    assert "DISABLED" in body, "the disabled reader is not recorded as disabled"


def test_every_page_is_sent_when_there_is_nothing_to_select_against():
    """Page selection exists to spend the model only where the deterministic reader left a
    gap. With A off the whole document is a gap, and a skipped page would read in the output
    as a page with no BOM on it."""
    assert re.search(r"if llm_only:\s*\n\s*#.*\n(\s*#.*\n)*\s*worth = None", _MERGE), (
        "page selection still applies, so pages are skipped for having no gap to fill")


def test_an_explicit_argument_still_wins_over_the_environment():
    """The env default exists so the flag need not be threaded through file_scan's signature.
    A caller that passes llm_only explicitly must not be second-guessed by a variable
    somebody left set in a shell."""
    at = _MERGE.index("if llm_only is None:")
    assert "SDI_LLM_ONLY" in _MERGE[at:at + 300]
    sig = _MERGE[_MERGE.index("def reconcile_job"):_MERGE.index("def reconcile_job") + 400]
    assert "llm_only=None" in sig, "the parameter defaults to a value, so the env is ignored"


# ── it cannot be mistaken for an estimate ────────────────────────────────────

def test_the_run_says_what_it_is_every_time():
    """THE ASSERTION THAT MATTERS. A diagnostic that produces a workbook looks exactly like an
    estimate that produced one. Nothing in the sheet, the flags or the totals says which it
    was."""
    block = _flag_block()
    assert "LLM-ONLY RUN" in block
    for said in ("not an estimate", "no BOM LINE is corroborated"):
        assert said in block, f"the banner does not say {said!r}"


def test_the_banner_does_not_claim_more_than_the_flag_does():
    """IT SAID "Nothing corroborates anything" AND THAT WAS NOT TRUE.

    --llm-only disables Path A of the BOM merge, the DXF flat patterns and the SolidWorks
    extract. It does NOT disable the PDF text layer: extract_with_pdfplumber is called
    unconditionally in extract_pdf_summary, and SDI_LLM_ONLY is read in exactly one production
    place — merge_boms — so material, thickness and the title-block fields are read on a
    measurement run exactly as on a full one.

    So twenty parts on the 10575-02 measurement legitimately carried material and thickness
    from "the drawing", and a banner announcing that nothing was corroborated contradicted the
    report's own provenance table. James: "Don't say 'vision model alone / DXF and extract off'
    if pdfplumber still read title blocks."

    OVERCLAIMING IS NOT THE SAFE DIRECTION. A warning a reader can disprove from the next page
    is one they discount, and the thing it was overstating — that no BOM LINE has a second
    reader — is true, serious, and the whole reason the flag exists."""
    block = _flag_block()
    assert "Nothing corroborates anything" not in block, (
        "the banner claims nothing was corroborated on a run whose title-block reads are "
        "corroborated exactly as usual")
    assert "pdfplumber" in block, (
        "the banner does not say the drawing's text was still read, so a reader takes "
        "'LLM-only' at face value and distrusts the fields that came off the sheet")


def test_the_help_text_scopes_the_flag_to_the_bom():
    """Somebody reaching for --llm-only is asking a question, and the flag answers a narrower
    one than its name suggests: what does the model make of this pack's BILL OF MATERIALS."""
    at = _MAIN.index('"--llm-only"')
    help_text = _MAIN[at:at + 1600]
    assert "TEXT LAYER IS STILL READ" in help_text
    assert "pdfplumber" in help_text


def test_it_says_the_numbers_must_not_be_quoted():
    block = _flag_block()
    assert re.search(r"not be quoted", block), (
        "nothing warns against quoting a figure produced with one reader and no corroboration")


def test_the_help_text_says_it_is_a_measurement():
    """Somebody reading --help months from now is the person most likely to reach for this
    and least likely to know what it costs them."""
    at = _MAIN.index('"--llm-only"')
    help_text = _MAIN[at:at + 1200]
    assert "MEASUREMENT, NOT ESTIMATING" in help_text
    assert "not a quote" in help_text
