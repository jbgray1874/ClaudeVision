"""record_merge.py — when two readings describe one thing, merge them FIELD BY FIELD.

Three places in this pipeline meet the same situation: two records that describe one
real line, and a rule for deciding which record wins. Every one of them resolved it the
same way — pick a winner, `dict(winner)`, discard the loser — and that is wrong in a way
that is invisible in the output, because the surviving record looks complete:

  * ``merge_boms.reconcile_page``: Path A read the code and the quantity off the text
    layer; Path B read the same line with vision and also read a description. The rows
    agree, so A wins, so ``dict(a)`` is emitted — and the description that only vision
    saw is gone. Nothing is flagged, because nothing disagreed.

  * ``file_scan.merge_job_pdf_summaries``: one BOM line appears on two drawings in a
    job folder. The primary PDF's row wins on principle, even when the other PDF's row
    is the one carrying the quantity. The primary's blank column stays blank.

  * ``merge_boms.merge_pages_into_parents``: a parts list continues onto a second sheet
    and the fitter's fixings table repeats it. The first sheet's row is kept and the
    second is recorded only as "also seen here" — so a column the first sheet clipped
    and the second sheet printed in full is never read.

Discarding the loser is not a rounding error. A record's fields are read independently
by everything downstream, and a reader that has no description prices differently from
one that has it. The winner of a row-level contest is the better record OVERALL; it is
not automatically the better record on EVERY field, and there is no reason to throw away
the fields where it is not.

WHAT THIS DOES. `merge_records` submits every field of the losing record through
``source_precedence.apply_field`` against the winner. That gets three behaviours from
one call, all of them the ones already agreed for this codebase:

    the winner is empty here      the loser fills the gap, stamped with ITS source
    both agree                    provenance upgrades to the stronger source
    both disagree                 precedence decides, and the disagreement is recorded
                                  on the record with both values and both sources

WHAT THIS DOES NOT DO. It does not re-decide the contest. Where a caller's own rule has
already arbitrated a field — vision wins on code and quantity when the two readers
disagree, which is a decision taken deliberately and against rank — that field is passed
as `decided`, and the loser's value for it is never submitted, only noted. Precedence
would otherwise quietly reverse a rule somebody chose on purpose, which is the same
class of silent overwrite this module exists to stop.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from source_precedence import MISSING, apply_field, source_of, value_of

__all__ = ["merge_records", "BOOKKEEPING_FIELDS"]

# Fields that describe the MERGE rather than the part. Carrying these across records
# would let one reading's audit trail be reported as the other's — the merge writing
# its own history rather than recording it.
BOOKKEEPING_FIELDS: Tuple[str, ...] = (
    "source", "confidence", "flag", "sheet", "also_on_sheets", "source_pdf",
    "review_flags", "merge_notes", "page", "page_index",
)


def _mergeable_fields(record: Dict[str, Any], skip: Iterable[str]) -> List[str]:
    """The data fields on a record: not its provenance stamps, not its bookkeeping.

    ``*_source`` and ``*_confidence`` are excluded because they are carried by
    ``apply_field`` alongside the value they describe. Submitting them as fields in
    their own right would let a source label travel without the observation that
    earned it — a record stamped `solidworks_api` on a value SolidWorks never saw.
    """
    _skip = set(skip)
    out: List[str] = []
    for key in record:
        if key in _skip:
            continue
        if key.endswith("_source") or key.endswith("_confidence"):
            continue
        if key.startswith("_"):
            continue
        out.append(key)
    return out


def merge_records(
    winner: Dict[str, Any],
    loser: Dict[str, Any],
    *,
    winner_source: str,
    loser_source: str,
    decided: Sequence[str] = (),
    skip: Iterable[str] = BOOKKEEPING_FIELDS,
    label: str = "",
) -> List[str]:
    """Fold `loser` into `winner` field by field, under precedence. Mutates `winner`.

    `winner_source` / `loser_source` name what READ each record — `bom_tree` for a
    parts table read off the text layer, `llm_extract` for one read by vision. They are
    the ranks precedence arbitrates with, so naming them honestly is the whole contract:
    a vision reading labelled `bom_tree` would displace a deterministic one.

    `decided` names fields the caller's own rule has already settled. Those keep the
    winner's value whatever their ranks say; a differing value on the loser is recorded
    as a note rather than applied, so the choice stays visible.

    Returns human-readable notes describing what the merge did — every gap filled and
    every field where the two records disagreed. Callers should surface these; a merge
    that fills six columns and says nothing is indistinguishable from one that fills
    none.
    """
    if not isinstance(winner, dict) or not isinstance(loser, dict):
        return []

    _decided = {str(f) for f in decided}
    _prefix = f"{label}: " if label else ""
    notes: List[str] = []

    # ATTACH THE WINNER'S OWN PROVENANCE FIRST. Rows arrive from the readers with values
    # and no source, which ranks them at zero — so submitting the loser's fields against
    # an unstamped winner would let the WEAKER reading overwrite the stronger one simply
    # because the stronger one never said who read it. Stamping first is what makes the
    # arbitration below mean anything.
    for field in _mergeable_fields(winner, skip):
        _v = value_of(winner, field)
        if _v is not MISSING and not source_of(winner, field):
            apply_field(winner, field, _v, winner_source)

    for field in _mergeable_fields(loser, skip):
        _new = value_of(loser, field)
        if _new is MISSING:
            continue
        _cur = value_of(winner, field)

        if field in _decided:
            # The caller already chose. Say so where the two differ; changing it here
            # would silently reverse a rule taken on purpose.
            if _cur is not MISSING and str(_cur).strip() != str(_new).strip():
                notes.append(
                    f"{_prefix}{field}: kept '{_cur}' from {winner_source} — "
                    f"{loser_source} read '{_new}'. This field was decided by the "
                    f"reconciliation rule, not by source rank")
            continue

        _was_empty = _cur is MISSING
        _before_src = source_of(winner, field)
        if apply_field(winner, field, _new, loser_source):
            if _was_empty:
                notes.append(
                    f"{_prefix}{field}: '{_new}' filled from {loser_source} — "
                    f"the {winner_source} reading had nothing here")
            else:
                notes.append(
                    f"{_prefix}{field}: '{_cur}' from {_before_src or winner_source} "
                    f"replaced by '{_new}' from {loser_source}, which outranks it")
        elif not _was_empty and str(_cur).strip() != str(_new).strip():
            notes.append(
                f"{_prefix}{field}: the two readings disagree — '{_cur}' from "
                f"{_before_src or winner_source} was kept, '{_new}' from "
                f"{loser_source} was not applied")

    if notes:
        _existing = winner.get("merge_notes")
        winner["merge_notes"] = list(_existing or []) + notes
    return notes
