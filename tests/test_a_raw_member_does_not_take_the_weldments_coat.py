"""A weldment whose own sheet says POWDER COATED keeps its coat when its members say RAW.

12645 (Tesco DRS External Shelter), 19:17 book on 8fe2bc5. The DOOR 12645-03GA (67.9 kg) and
the DOOR FRAME 12645-02GA both state SURFACE FINISH: POWDER COATED on their own title block;
every member sheet under them states RAW (formed raw, welded, then coated as one object). The
book coated no part of the door at all, and coated only the frame's bottom panel and its 16
square nuts (one P.Coat row, qty 17) while the two heel posts and the top column went bare.

Two passes did it between them. The document-level stamp put a powder op on every steel
member, RAW or not. The parent dedup then counted those members as "coated on their own line"
and stood the weldment's coat down — before the finish gate ruled the members' own coats out
for RAW. Each member's two claims then tied at one rank and the claim id settled it.

The reading was right: the members ARE raw (an earlier note blamed a garbled copyright line;
the SURFACE FINISH box itself says RAW). The fix (D-320) is in both passes: the stamp does not
coat a part whose own sheet states another finish, and the dedup does not count a member the
finish gate would rule out.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest  # noqa: E402

from route_compiler import NOT_APPLICABLE, REQUIRED, compile_job_route  # noqa: E402


def _member(pn, finish, stamped):
    m = {"part_number": pn, "description": "PANEL", "quantity": 1,
         "normalized_material": "MILD_STEEL",
         "normalized_finish": finish, "surface_finishes": [finish],
         "textual_operations": ["laser_cutting"]}
    if stamped:   # another reader's REQUIRED powder claim on the member, as the old stamp wrote it
        m.update(inferred_operations=["powder_coating"],
                 operation_sources={"powder_coating": "drawing_deterministic"},
                 finish_inherited_from="document_level")
    return m


def _powder(member_finish, stamped):
    parts = [{"part_number": "W-GA", "description": "DOOR", "quantity": 1,
              "normalized_material": "MILD_STEEL", "normalized_finish": "POWDER COATED",
              "surface_finishes": ["POWDER COATED"],
              "textual_operations": ["welding", "powder_coating"]}]
    parts += [_member(f"W-0{i}M", member_finish, stamped) for i in (1, 2, 3)]
    extract = {"assemblies": [{"part_number": "W-GA", "children": [
        {"part_number": f"W-0{i}M", "qty": 1} for i in (1, 2, 3)]}],
        "parts": [], "routes": []}
    return {d["target_id"]: d for d in compile_job_route(parts, extract)["decisions"]
            if d["operation"] == "powder_coating"}


@pytest.mark.parametrize("stamped", [False, True], ids=["unstamped", "a-reader-stamped-them"])
def test_raw_members_leave_the_coat_on_the_weldment(stamped):
    """Whether or not some reader put powder on the RAW members, the weldment is the object
    in the booth and keeps its coat."""
    pw = _powder("RAW", stamped)
    assert pw["W-GA"]["status"] == REQUIRED, \
        f"the weldment is the object in the booth: {pw['W-GA']['reason']}"


def test_unstamped_raw_members_are_not_coated_on_their_own_line():
    pw = _powder("RAW", stamped=False)
    for pn in ("W-01M", "W-02M", "W-03M"):
        assert pn not in pw or pw[pn]["status"] != REQUIRED, pw[pn]["reason"]


def test_members_whose_own_sheets_say_powder_still_carry_the_coat():
    """The 11350 shape is unchanged: members coated on their own lines, the parent stands
    down as the finish statement rather than a second object in the booth."""
    pw = _powder("POWDER COATED", stamped=True)
    assert all(pw[pn]["status"] == REQUIRED for pn in ("W-01M", "W-02M", "W-03M"))
    assert pw["W-GA"]["status"] != REQUIRED


def test_the_document_stamp_does_not_coat_a_part_whose_sheet_says_raw():
    """The stamp at source: a part stating RAW on its own sheet is not given the document's
    powder op; a part stating nothing still is."""
    import estimator
    raw = {"part_number": "W-01M", "normalized_material": "MILD_STEEL",
           "normalized_finish": "RAW", "surface_finishes": ["RAW"], "quantity": 1}
    silent = {"part_number": "W-04M", "normalized_material": "MILD_STEEL", "quantity": 1}
    summary = {"document_analysis": {"title_block": {"surface_finishes": ["POWDER COATED"]}}}
    try:
        estimator.estimate_document([raw, silent], summary)
    except Exception:
        pass   # only the stamp is under test; costing an unmeasured part may refuse
    assert "powder_coating" not in (raw.get("inferred_operations") or []), raw
    assert "powder_coating" in (silent.get("inferred_operations") or []), silent
