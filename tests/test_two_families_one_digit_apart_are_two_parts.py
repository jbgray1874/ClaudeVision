"""TWO FAMILIES ONE DIGIT APART ARE TWO PARTS, NOT A MISPRINT (20 Nov 2026).

12133-00-GA, run e2ab30cc6d62: 12133-05-101 and 12133-06-101 were joined as "one digit apart"
(D-749) because their descriptions share a word and the pack's other codes carry the
spelling. But the pack carries BOTH families (05-01M.. and 06-01M..), and the model lists the two
sub-assemblies apart, at 6 and 3. The digit is a misprint only where the other codes carry
ONE of the two spellings, as on 0358141. Invented numbers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part_identity import corroborated_near_code  # noqa: E402


def test_two_real_families_are_not_joined():
    ctx = ["50007-05-01M", "50007-05-02M", "50007-06-01M", "50007-06-02M", "50007-05-101"]
    assert corroborated_near_code("50007-05-101", "HOLDER WELD ASSY",
                                  {"50007-06-101": "HOLDER WELD ASSY"}, ctx) is None


def test_the_misprint_with_one_family_is_still_joined():
    # D-749's shape: the siblings all carry 0358141; the parts list printed 0358131 once
    ctx = ["UPC0358141 M1", "UPC0358141 M2", "UPC0358141 M6"]
    assert corroborated_near_code("UPC0358141 M7", "BASE END CAP",
                                  {"UPC0358131 M7": "BASE END CAP"}, ctx) == "UPC0358131 M7"
