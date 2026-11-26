"""FINISHED PART NO. is not a finish label (Hotel Chocolat, Wall of Chocolate, 26 Nov 2026).

Every Hotel Chocolat title block prints "FINISHED PART NO.<stock code>". The finish reader
matched the FINISH inside FINISHED and took what followed as the finish: the WOC box's
"finish stated" read "ED PART NO.00026207", and a sheet that also printed SURFACE FINISH:
ZINC PLATED lost that to it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import FINISH_PATTERN  # noqa: E402
from extractor_patterns import _extract_finish_candidates  # noqa: E402


def test_a_finished_part_number_is_not_read_as_a_finish():
    assert _extract_finish_candidates("FINISHED PART NO.00026207 ITEM NO. DRG NO") == []
    assert not re.findall(FINISH_PATTERN, "FINISHED PART NO.00026207", flags=re.I)


def test_the_real_finish_beside_it_is_read():
    found = _extract_finish_candidates("FINISHED PART NO.10100277 SURFACE FINISH: ZINC PLATED")
    assert found and "ZINC PLATED" in found[0] and "PART NO" not in " ".join(found)
    assert _extract_finish_candidates("FINISH: POWDER COAT RAL 9005 MATERIAL: MDF") == \
        ["POWDER COAT RAL 9005"]
