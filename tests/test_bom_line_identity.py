"""
A BOM line is (parent, code), not code.

Job 12392 is one enquiry with two general arrangements: 02 uses 16 M4x8 fixings, 04 uses 4
more. The readers recorded both, each stamped with the drawing it came from. A rollup keyed
on the part number kept one line of 16 and dropped the other, taking its quantity and its
parent edge with it — which is also how the 04 brackets arrived at costing as orphans and
were then classified as things we buy.

These tests hold the two halves of that failure apart, because they are separate defects that
happened to fire together:

    the MERGE   — two assemblies' use of one part must survive as two lines
    the READING — a material text we cannot resolve must not outrank the drawing's own
                  numbering convention, nor make a part we cut look purchased

Every guard here is mutation-tested: each is shown failing on the input it exists to reject
before it is shown passing on the input it exists to allow. A test that cannot produce the
condition it asserts on has proved nothing.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import bay_rollup
import bought_in_policy
import invariants
import json_normaliser
import part_code_conventions


# ── the drawing's own numbering convention ──────────────────────────────────────────────

def test_the_convention_is_readable_not_only_strippable():
    """base_code has always REMOVED this letter; nothing could ask what it said."""
    assert part_code_conventions.material_suffix("12392-04-01M") == "M"
    assert part_code_conventions.material_suffix("11350-01-02A") == "A"
    assert part_code_conventions.material_suffix("1449-03-07T") == "T"
    # A code that merely ends in a letter is not a material statement.
    assert part_code_conventions.material_suffix("12392-02-GA") == ""
    assert part_code_conventions.material_suffix("12392-02-17G") == ""
    assert part_code_conventions.material_suffix("TBM571") == ""
    assert part_code_conventions.material_suffix("") == ""
    # It must agree with the stripper that has always been in this module.
    assert part_code_conventions.base_code("12392-04-01M")[0] == "12392-04-01"


def _material(part_number: str, material: str, description: str = "BRACKET") -> str:
    return json_normaliser.normalise_material_for_part(
        {"part_number": part_number, "materials": [material], "description": description})


def test_unresolvable_material_text_does_not_silence_the_convention():
    """The gate asked whether the text was ABSENT; it means whether the text SAID anything.

    On a blank drawing those are the same question. On a noisy one they are not, and the
    noisy one is the common case: 12392's steel brackets read "Card 2mm", which is not blank
    and resolves to nothing, so the convention never got to speak and the parts reached
    costing with no material at all.
    """
    # MUTATION: the exact condition the old hand-written blacklist could not see.
    assert json_normaliser.normalise_material("Card 2mm") is None, \
        "if this ever resolves, this test is no longer exercising an unresolvable token"
    assert _material("12392-04-01M", "Card 2mm") == "MILD_STEEL"
    assert _material("12392-04-02M", "N/A") == "MILD_STEEL"
    assert _material("12392-04-02M", "TBC") == "MILD_STEEL"
    assert _material("12392-04-01M", "SEE DRAWING") == "MILD_STEEL"
    # The four tokens the old blacklist listed by hand are a subset, not a special case.
    for token in ("LED", "CARD", "VINYL", "TAPE"):
        assert _material("12392-04-01M", token) == "MILD_STEEL"
    # And the other two letters mean what the convention says they mean.
    assert _material("1449-03-07T", "Card") == "MDF"
    assert _material("11350-01-02A", "Card", "PANEL") == "ACRYLIC"


def test_a_material_the_drawing_states_still_beats_the_convention():
    """A suffix is a naming convention, not an observation. It speaks only where the
    drawing did not — otherwise the Horti Crate regression returns, where -J panels the
    BOM prices as timber were forced to steel and routed to laser, weld and powder."""
    assert _material("11350-01-01M", "OAK", "SHELF") == "TIMBER"
    assert _material("11350-01-01T", "MILD STEEL", "PANEL") == "MILD_STEEL"
    assert _material("11350-01-02A", "MDF", "PANEL") == "MDF"
    assert _material("12392-04-01M", "ALUMINIUM") == "ALUMINIUM"


def test_readings_that_blanking_the_noise_would_have_lost():
    """The old rule CLEARED the material text. Generalising that would have been wrong:
    PMMA and DISPA also resolve to nothing, and branches below read them as substrings."""
    assert json_normaliser.normalise_material("PMMA") is None
    assert json_normaliser.normalise_material("DISPA") is None
    assert _material("P1", "PMMA", "WINDOW") == "ACRYLIC"
    assert _material("P1", "DISPA BOARD", "SIGN") == "BOUGHT_IN"


def test_a_code_with_no_convention_letter_is_unchanged():
    """The fix may only speak where the numbering convention does. An assembly whose
    material reads as noise still resolves to nothing, exactly as before."""
    assert _material("12392-02-201", "Card", "ASSEMBLY") is None
    assert _material("TBM571", "Card", "STANDOFF") is None


# ── make or buy ─────────────────────────────────────────────────────────────────────────

def test_the_numbering_convention_stops_the_bought_in_default():
    """"We could not identify the material" is the weakest signal there is, and a part
    number written by the person who drew it is a positive statement against it."""
    # MUTATION: without a convention letter the default still fires — so the guard below
    # is the thing making the difference, not some other rule.
    assert bought_in_policy.bought_in_reason(
        {"part_number": "12392-02-201", "normalized_material": "BOUGHT_IN"})
    assert not bought_in_policy.bought_in_reason(
        {"part_number": "12392-04-01M", "normalized_material": "BOUGHT_IN"})
    assert not bought_in_policy.is_bought_in(
        {"part_number": "12392-04-02M", "material": "BOUGHT_IN"})


def test_catalogue_identity_still_outranks_the_convention():
    """The cost of getting THIS one wrong is laser and fold time booked against something we
    simply buy, so every strong signal must survive a code that ends in a material letter."""
    for part, expected in (
        ({"part_number": "BI-BOLT01M", "normalized_material": "BOUGHT_IN"}, "code family"),
        ({"part_number": "12392-04-01M", "is_bought_in": True}, "flagged"),
        ({"part_number": "12392-04-01M", "page_roles": ["bought_in"]}, "page"),
        ({"part_number": "12392-04-01M", "source": "bought_in_recogniser"}, "source"),
        ({"part_number": "12392-04-01M", "material_family": "bought_in"}, "purchased"),
    ):
        assert expected in bought_in_policy.bought_in_reason(part), part


# ── the merge ───────────────────────────────────────────────────────────────────────────

def _fixings_under_two_gas():
    """One enquiry, two general arrangements, the same fastener on both."""
    return [
        {"part_number": "12392-02-01M", "description": "PANEL", "quantity": 1,
         "bom_parent": "12392-02-GA", "source": "document_analysis"},
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4x8", "quantity": 16,
         "bom_parent": "12392-02-GA", "source": "document_analysis"},
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4x10", "quantity": 4,
         "bom_parent": "12392-04-GA", "source": "document_analysis"},
        {"part_number": "12392-04-01M", "description": "MOD MOUNT BRACKET", "quantity": 2,
         "bom_parent": "12392-04-GA", "source": "document_analysis"},
    ]


def test_two_assemblies_using_one_part_are_two_lines():
    rows = bay_rollup.dedupe_bom_rows_for_bay_rollup(_fixings_under_two_gas(), [])
    fixings = [r for r in rows if bay_rollup._row_code(r) == "FIXING"]
    assert len(fixings) == 2, f"a line was merged away: {fixings}"
    assert {r["bom_parent"] for r in fixings} == {"12392-02-GA", "12392-04-GA"}
    # The quantities are the point: 16 and 4 are different orders of the same screw.
    assert sorted(r["quantity"] for r in fixings) == [4, 16]
    # And every parent edge survives, for every part.
    assert {(bay_rollup._row_code(r), bay_rollup._row_parent(r)) for r in rows} == {
        ("12392-02-01M", "12392-02-GA"), ("FIXING", "12392-02-GA"),
        ("FIXING", "12392-04-GA"), ("12392-04-01M", "12392-04-GA"),
    }


def test_the_same_line_read_twice_is_still_one_line():
    """Splitting requires two recorded PARENTS, not two rows. Two readers seeing the same
    line must still collapse, or every job double-counts."""
    rows = [
        {"part_number": "FIXING", "description": "SCREW", "quantity": 16,
         "bom_parent": "12392-02-GA", "source": "document_analysis"},
        {"part_number": "FIXING", "description": "SCREW M4x8", "quantity": 16,
         "bom_parent": "12392-02-GA", "source": "bay_bom"},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert len(out) == 1
    assert out[0]["source"] == "bay_bom", "source priority must still decide the winner"


def test_a_row_with_no_recorded_parent_never_becomes_a_second_line():
    """A catalogue scan or a synthesized fallback records no owner. It cannot be shown to be
    a separate line, so it must join the parented one rather than count the part twice."""
    rows = [
        {"part_number": "TBM571", "description": "STANDOFF", "quantity": 8,
         "bom_parent": "12392-02-GA", "source": "document_analysis"},
        {"part_number": "TBM571", "description": "STANDOFF", "quantity": 8,
         "source": "assembly_text_catalogue"},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert len(out) == 1, f"the unparented row was counted as a second line: {out}"


def test_a_job_with_no_parent_evidence_behaves_exactly_as_before():
    """The safety property that lets this run everywhere: with nothing recorded, line
    identity degenerates to code identity by construction, not by a flag."""
    rows = [
        {"part_number": "FIXING", "description": "SCREW", "quantity": 16},
        {"part_number": "FIXING", "description": "SCREW", "quantity": 4},
        {"part_number": "12392-02-01M", "description": "PANEL", "quantity": 1},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert sorted(bay_rollup._row_code(r) for r in out) == ["12392-02-01M", "FIXING"]


def test_source_pdf_is_a_parent_when_no_page_label_was_recorded():
    """The folder merge stamps source_pdf on every row, so even a reader that records no
    page label still tells two drawings apart."""
    rows = [
        {"part_number": "FIXING", "description": "SCREW", "quantity": 16,
         "source_pdf": "12392-02-GA.pdf"},
        {"part_number": "FIXING", "description": "SCREW", "quantity": 4,
         "source_pdf": "12392-04-GA.pdf"},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert len(out) == 2


# ── and the check that says so when it stops holding ────────────────────────────────────

def _summary(raw, final):
    return {"document_analysis": {"bom_rows": raw, "bay_bom_rows": final}}


def test_the_check_catches_a_collapsed_line():
    raw = _fixings_under_two_gas()
    collapsed = [r for r in raw if r is not raw[2]]        # the 04 fixing line, merged away
    found = invariants.check_bom_lines_survive_the_merge(_summary(raw, collapsed))
    assert len(found) == 1
    assert found[0]["code"] == "bom_lines_collapsed_by_part_number"
    assert found[0]["severity"] == invariants.BLOCKING
    assert found[0]["detail"]["lines_lost"] == 1
    assert found[0]["detail"]["parts"][0]["part_number"] == "FIXING"


def test_the_check_passes_the_merge_it_is_watching():
    raw = _fixings_under_two_gas()
    assert invariants.check_bom_lines_survive_the_merge(
        _summary(raw, bay_rollup.dedupe_bom_rows_for_bay_rollup(raw, []))) == []


def test_the_check_does_not_claim_a_wholly_dropped_code():
    """Drawing furniture, a weldment parent shadowed by its children, a catalogue
    reclassification — those remove a code entirely and are governed elsewhere. Partial
    survival cannot be any of them, which is why only partial survival is claimed here."""
    raw = _fixings_under_two_gas()
    assert invariants.check_bom_lines_survive_the_merge(
        _summary(raw, [r for r in raw if bay_rollup._row_code(r) != "FIXING"])) == []


def test_the_check_is_silent_where_there_is_no_merge_to_check():
    assert invariants.check_bom_lines_survive_the_merge({"document_analysis": {}}) == []
    assert invariants.check_bom_lines_survive_the_merge(
        _summary(_fixings_under_two_gas(), [])) == []


def test_the_check_reports_that_it_verified_nothing_when_it_cannot_run():
    found = invariants.check_bom_lines_survive_the_merge("not a job")
    assert len(found) == 1
    assert found[0]["severity"] == invariants.UNVERIFIED


def test_the_check_is_registered():
    """A check that is written and never called is the defect it was written to catch."""
    assert invariants.check_bom_lines_survive_the_merge in invariants.CHECKS


# ── the six-defect punch list from the live 12392 run ───────────────────────────────────

def test_a_drawing_number_is_read_from_a_real_file_name():
    """DEFECT 1, AND IT EXPLAINED THE OTHER FIVE. job_drawing_numbers took the whole stem, so
    "12392-04-GA Mod Bracket Set_revA.pdf" produced "12392-04-GA MOD BRACKET SET_REVA" and
    matched the BOM's parent "12392-04-GA" nowhere. Estimating names drawings
    "<number> <what it is>_rev<x>" — a convention, not prose."""
    from route_compiler import job_drawing_numbers as jdn

    def one(name):
        return jdn({"job_source_pdfs": [{"name": name}]})

    assert one("12392-04-GA Mod Bracket Set_revA.pdf") == ["12392-04-GA"]
    assert one("12422-24-GA_End Cap_RevB.pdf") == ["12422-24-GA"]
    assert one("12392-02-GA.pdf") == ["12392-02-GA"]
    # The spaced forms merge_boms documents, and the trap in them: the head alone is
    # "12392-04", a perfectly good drawing number and the wrong one.
    assert one("12392-04 - GA.pdf") == ["12392-04-GA"]
    assert one("1282 - GA.pdf") == ["1282-GA"]
    assert one("1450 GA.pdf") == ["1450-GA"]
    # The safety this replaced a blanket refusal with: a name that is not a number yields
    # nothing, because a drawing whose number we cannot read must not head a tree.
    assert one("Mod mount bracket set.pdf") == []
    assert one("Drawing1.pdf") == []
    assert one("Scan_001.pdf") == []


def test_one_parent_may_list_a_code_twice():
    """DEFECT 2. 12392-04-GA carries FIXING M4x8 and FIXING M4x10 — generic code, two
    different bolts, two quantities. Keyed on (parent, code) the second line vanished, which
    is the part-number collapse again, one level in."""
    import bay_rollup
    rows = [
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4X8", "quantity": 16,
         "bom_parent": "12392-02-GA"},
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4X8", "quantity": 4,
         "bom_parent": "12392-04-GA"},
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4X10", "quantity": 4,
         "bom_parent": "12392-04-GA"},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert len(out) == 3, f"a line was merged away: {[r['description'] for r in out]}"
    under_04 = sorted(r["description"] for r in out if r["bom_parent"] == "12392-04-GA")
    assert under_04 == ["BUTTON HEAD SCREW M4X10", "BUTTON HEAD SCREW M4X8"]


def test_but_two_readers_spelling_one_line_still_merge():
    """The reason description cannot simply join the key: a deterministic table reads "SCREW"
    where vision reads "BUTTON HEAD SCREW M4x8". Keying on the text would split one line in
    two and count the fastener twice. Containment, not equality."""
    import bay_rollup
    rows = [
        {"part_number": "FIXING", "description": "SCREW", "quantity": 16,
         "bom_parent": "12392-02-GA", "source": "document_analysis"},
        {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4X8", "quantity": 16,
         "bom_parent": "12392-02-GA", "source": "bay_bom"},
    ]
    out = bay_rollup.dedupe_bom_rows_for_bay_rollup(rows, [])
    assert len(out) == 1
    assert out[0]["source"] == "bay_bom", "source priority still decides the winner"


def test_a_page_role_that_contradicts_itself_is_not_authority():
    """DEFECT 3. The brackets carry BOTH "detail" and "bought_in" — two readings of one code
    disagreeing, not a catalogue statement. Taken as decisive it stripped the laser and the
    fold from two steel brackets the workbook then had to put back."""
    import bought_in_policy as bp
    assert not bp.is_bought_in(
        {"part_number": "12392-04-01M", "page_roles": ["detail", "bought_in"]})
    # One signal alone is still decisive: a bought-in page on its own, or a mixed reading on
    # a code that carries no material-suffix convention of ours.
    assert bp.is_bought_in({"part_number": "12392-04-01M", "page_roles": ["bought_in"]})
    assert bp.is_bought_in({"part_number": "TBM571", "page_roles": ["detail", "bought_in"]})
    # And every stronger rule is checked first, so none of them can be reached by this.
    for stronger in ({"is_bought_in": True},
                     {"source": "bought_in_recogniser"},
                     {"material_family": "bought_in"}):
        part = {"part_number": "12392-04-01M", "page_roles": ["detail", "bought_in"]}
        part.update(stronger)
        assert bp.is_bought_in(part), stronger
    assert bp.is_bought_in({"part_number": "BI-X01M", "page_roles": ["detail", "bought_in"]})
