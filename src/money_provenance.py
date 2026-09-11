"""Does this saved record carry the money, or only what was handed to the spreadsheet?

THE WEEK THIS COST. Twenty-three archived 7332-01 records were searched for the run behind an
accepted GBP 80.09 workbook. Every one of them looked like a candidate: right job, right
quantity, right part count, plausible timestamps. Not one could evidence the accepted price,
because not one carried `final_estimate.totals` — and nothing in any of them said so. The
absence was discoverable only by running the costing code and noticing the totals came back
None, which is exactly the kind of thing nobody notices until they need it.

A record that cannot evidence a price must SAY it cannot. That is all this module does: it reads
a record, decides which of three states it is in, and names the evidence for that decision, so
the fact is on the file rather than inferable from it.

    excel_calculated      final_estimate.totals is present, read back off the calculated sheet.
                          This record can evidence what the job was priced at.
    accepted_rows_only    the workbook's accepted row grouping reached the record but its
                          calculated totals did not. Parts and operations are attributable;
                          money is not.
    pre_workbook          neither. The record holds what the engine handed TO Excel. Its own
                          line sums are a DIFFERENT CALCULATOR from the sheet's, so a
                          difference between them is not a defect in either figure — and the
                          accepted price is simply not in here.

WHY A RECORD CAN BE PRE-WORKBOOK WITHOUT ANYTHING BEING BROKEN. populate_workbook returns a path
or nothing, and the read-back needs Excel COM. On a machine without Excel, on a run where the
workbook stage was skipped, or where the read-back raised, the run continues deliberately: an
estimate that fails because a diagnostic could not open a spreadsheet is worse than one that
completes and says what it lacks. The defect was never that this happens. It was that the saved
record did not mention it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

SCHEMA = "money_provenance.v1"

EXCEL_CALCULATED = "excel_calculated"
ACCEPTED_ROWS_ONLY = "accepted_rows_only"
PRE_WORKBOOK = "pre_workbook"

# The three figures an accepted price rests on. Named so a partial read-back — totals present
# but one of them null, which Excel errors produce — is reported as partial rather than whole.
TOTAL_KEYS = ("material_gbp", "labour_gbp", "unit_gbp")


def _block(record: Mapping[str, Any], key: str) -> Dict[str, Any]:
    """A top-level block or its estimate_summary twin, whichever exists. Both spellings are
    live in this pipeline and a reader that knows only one reports a present block as absent."""
    for holder in (record, record.get("estimate_summary") if isinstance(record, Mapping) else None):
        if isinstance(holder, Mapping) and isinstance(holder.get(key), Mapping):
            return dict(holder[key])
    return {}


def _rows(record: Mapping[str, Any], key: str, field: str) -> Optional[List[Any]]:
    block = _block(record, key)
    rows = block.get(field)
    return list(rows) if isinstance(rows, list) else None


def describe(record: Mapping[str, Any], skip_reason: str = "") -> Dict[str, Any]:
    """The record's money provenance, with the evidence for it.

    `skip_reason` is what the run itself knows and the file cannot show: "Excel COM unavailable",
    "populate_workbook returned no path". Recording it turns "this record has no totals" into
    "this record has no totals BECAUSE", which is the difference between a mystery and a repair.
    """
    if not isinstance(record, Mapping):
        return {"schema": SCHEMA, "state": PRE_WORKBOOK,
                "can_evidence_a_price": False,
                "why": "not a record", "evidence": {}}

    final_estimate = _block(record, "final_estimate")
    totals = final_estimate.get("totals") if isinstance(
        final_estimate.get("totals"), Mapping) else {}
    present = [k for k in TOTAL_KEYS if totals.get(k) is not None]
    missing = [k for k in TOTAL_KEYS if totals.get(k) is None]
    labour_rows = _rows(record, "final_estimate", "labour_rows")
    accepted_rows = _rows(record, "workbook_labour", "rows")

    evidence: Dict[str, Any] = {
        "final_estimate.totals": {"present": present, "missing": missing} if totals
                                 else "ABSENT",
        "final_estimate.labour_rows": len(labour_rows) if labour_rows is not None else "ABSENT",
        "workbook_labour.rows": len(accepted_rows) if accepted_rows is not None else "ABSENT",
        "final_estimate.source": final_estimate.get("source") or "",
        "final_estimate.schema": final_estimate.get("schema") or "",
    }
    if skip_reason:
        evidence["workbook_stage_skipped_because"] = skip_reason

    if present:
        state = EXCEL_CALCULATED
        why = ("final_estimate.totals was read back off the calculated sheet, so this record "
               "evidences what the job was priced at")
        if missing:
            why += (f" — except {', '.join(missing)}, which Excel returned as null "
                    f"(an error cell is missing data, never zero)")
    elif accepted_rows or labour_rows:
        state = ACCEPTED_ROWS_ONLY
        why = ("the workbook's accepted row grouping reached this record but its calculated "
               "totals did not, so parts and operations are attributable and money is not")
    else:
        state = PRE_WORKBOOK
        why = ("this record holds what the engine handed TO Excel, not what Excel produced. Its "
               "own line sums are a different calculator from the sheet's, so a difference "
               "between them is not a defect in either figure, and the accepted price is not "
               "in here")
        if skip_reason:
            why += f". The workbook stage was skipped: {skip_reason}"

    return {
        "schema": SCHEMA,
        "state": state,
        # THE FIELD EVERY CONSUMER SHOULD READ. One boolean, so nothing has to re-derive the
        # rule, and no surface can accidentally treat an engine sum as an accepted price.
        "can_evidence_a_price": state == EXCEL_CALCULATED and not missing,
        "why": why,
        "evidence": evidence,
    }


def stamp(record: Dict[str, Any], skip_reason: str = "") -> Dict[str, Any]:
    """Write the verdict into the record under `money_provenance` and return it."""
    verdict = describe(record, skip_reason=skip_reason)
    if isinstance(record, dict):
        record["money_provenance"] = verdict
    return verdict


def can_evidence_a_price(record: Mapping[str, Any]) -> bool:
    """Read the stamped verdict if there is one, else work it out. A consumer must not have to
    know which, and a stamped record must not be re-judged by a later, different rule."""
    stamped = record.get("money_provenance") if isinstance(record, Mapping) else None
    if isinstance(stamped, Mapping) and "can_evidence_a_price" in stamped:
        return bool(stamped.get("can_evidence_a_price"))
    return bool(describe(record).get("can_evidence_a_price"))


__all__ = ["SCHEMA", "EXCEL_CALCULATED", "ACCEPTED_ROWS_ONLY", "PRE_WORKBOOK", "TOTAL_KEYS",
           "describe", "stamp", "can_evidence_a_price"]
