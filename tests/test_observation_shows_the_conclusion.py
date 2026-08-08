"""A report that shows the loser of an arbitration is worse than one that shows nothing.

Job 12392 told an estimator four times that a part we cut in mild steel was "Card" — the
scrambled drawing text the arbitration had already rejected in favour of the SolidWorks
material. The costing was right on every one of them: raw 'Card', costed MILD_STEEL,
source solidworks_api.

Nothing was wrong with the engine and everything was wrong with the sentence. Someone
reading that against a steel bracket has been given a reason to distrust a sheet that was
correct — and that is expensive in a way a wrong number at least announces.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _observation(part):
    """The single material sentence document_builder would emit for this part."""
    source = (SRC / "document_builder.py").read_text(encoding="utf-8")
    block = source[source.index('if part["materials"]:'):]
    block = block[:block.index('if part["slot_detected"]')]
    ns = {"observations": [], "part": part, "pn": part["part_number"]}
    exec(compile(re.sub(r"^        ", "", block, flags=re.M), "<obs>", "exec"), ns)
    return ns["observations"][0] if ns["observations"] else ""


def test_the_rejected_reading_is_not_presented_as_the_material():
    line = _observation({
        "part_number": "12392-02-01M", "materials": ["Card"],
        "normalized_material": "MILD_STEEL", "material_source": "solidworks_api"})
    assert "material MILD_STEEL" in line
    assert "solidworks_api" in line
    assert "was not used" in line
    assert not line.startswith("12392-02-01M: material detected (Card)")


def test_the_reading_is_still_shown_because_it_is_evidence_of_a_bad_drawing():
    """Not hidden. A title block that reads as 'Card' on a steel part is worth knowing —
    it is just not the material, and the sentence has to say which is which."""
    line = _observation({
        "part_number": "12392-02-01M", "materials": ["Card"],
        "normalized_material": "MILD_STEEL", "material_source": "solidworks_api"})
    assert "'Card'" in line


def test_agreement_reads_as_it_always_did():
    """Mutation guard. Where the reading and the conclusion agree there is no arbitration
    to report, and the sentence must not grow a caveat that means nothing."""
    line = _observation({
        "part_number": "12392-02-201", "materials": ["MDF"],
        "normalized_material": "MDF", "material_source": "title_block"})
    assert line == "12392-02-201: material detected (MDF)."


def test_a_part_with_no_conclusion_still_reports_what_was_read():
    line = _observation({
        "part_number": "X", "materials": ["DIGITAL PRINT VINYL"],
        "normalized_material": None, "material_source": None})
    assert line == "X: material detected (DIGITAL PRINT VINYL)."


def test_underscored_family_names_count_as_agreement():
    """MILD_STEEL and "MILD STEEL" are the same answer spelled two ways, and reporting
    them as a disagreement would put a caveat on every correctly-read steel part."""
    line = _observation({
        "part_number": "Y", "materials": ["MILD STEEL"],
        "normalized_material": "MILD_STEEL", "material_source": "title_block"})
    assert line == "Y: material detected (MILD STEEL)."
