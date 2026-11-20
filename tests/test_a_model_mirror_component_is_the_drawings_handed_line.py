"""A MODEL'S MIRROR COMPONENT IS THE DRAWING'S HANDED LINE (20 Nov 2026).

12133-00-GA, run e2ab30cc6d62: the LED assembly 12133-02-01X holds a SolidWorks mirror
component "Mirror12133-02-01X" x6, the strip the GA lists as "12133-02-01X - HANDED" x6. The
model-to-drawing join offered only the MIR spellings and the bare base, so the mirror matched
nothing and the estimate carried a third LED line at 18 beside the base and the handed one.
The join now offers the drawing's hand words too, before the base. Invented numbers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import route_compiler as rc  # noqa: E402
from part_code_conventions import alias_targets  # noqa: E402
from part_identity import normalize_part_code  # noqa: E402


def test_the_mirror_joins_the_handed_line_when_the_drawing_lists_one():
    handed = normalize_part_code("50006-02-01X - HANDED")
    aliases = rc._drawing_code_aliases(["50006-02-01X", handed, "Mirror50006-02-01X"])
    assert aliases.get("MIRROR50006-02-01X") == handed, aliases


def test_a_mir_line_is_still_preferred_and_the_base_is_still_the_last_resort():
    assert alias_targets("Mirror50006-02-01X")[0] == "50006-02-01X MIR"
    assert alias_targets("Mirror50006-02-01X")[-1] == "50006-02-01X"
    aliases = rc._drawing_code_aliases(["50006-02-01X", "50006-02-01X MIR", "Mirror50006-02-01X"])
    assert aliases.get("MIRROR50006-02-01X") == "50006-02-01X MIR"
    # with no other hand listed, the base takes it, as before
    aliases = rc._drawing_code_aliases(["50006-02-01X", "Mirror50006-02-01X"])
    assert aliases.get("MIRROR50006-02-01X") == "50006-02-01X"
