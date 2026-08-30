"""
engine_discoveries.py — how many of this job's flags are OUR fault.

"IS IT GETTING QUIETER" HAS BEEN ANSWERED BY IMPRESSION, ON ONE DRAWING, FOR A WEEK. That is
not a measurement, and it is the only question that decides whether estimating can use this
tool. So it becomes a number.

THE DISTINCTION THAT MATTERS IS NOT SEVERITY. A BLOCKING flag saying "this material has no rate
in the catalogue" is the engine working perfectly: it read the drawing, priced what it could,
and told a person what only a person can settle. A WARNING saying "a part appears in the raw
records and not in the extract, so it was invented downstream" is the engine confessing. One
of those is Tim's list. The other is ours, and only ours should be trending to zero.

THE TEST FOR EACH CODE IS ONE QUESTION: would a PERFECT engine, reading this same pack, still
raise this? If yes it belongs to the drawing or to commerce — a missing rate, a gauge the model
and the export disagree about, a detail drawing nobody sent. If no, it is a discovery about
this codebase and it is the number that has to fall.

AN UNCLASSIFIED CODE COUNTS AS OURS. A new check added without deciding which it is inflates
the engine number rather than disappearing from it — because the failure mode of every metric
is that the inconvenient thing quietly stops being counted.
"""
from __future__ import annotations

from typing import Any, Dict, List

SCHEMA = "engine_discoveries.v1"

# WOULD A PERFECT ENGINE STILL RAISE THIS ON THIS PACK? Yes -> it belongs to the drawing or to
# commerce. These are estimating work, and a mature system produces MORE of them, not fewer,
# because it reads more of the pack and has more to say about it.
_NOT_OURS = {
    # Commerce: a price this business has not decided yet.
    "material_has_no_rate_in_this_engine",
    "price_not_reproducible",
    "price_not_firm",
    "stated_finish_not_costed",
    "short_run_pays_for_sheet_it_does_not_use",
    "bought_in_without_a_catalogue_price",
    # The drawing pack disagreeing with itself, or being incomplete.
    "two_sources_disagree_about_the_gauge",
    "two_sources_disagree_about_the_material",
    "handed_pair_disagrees",
    "handed_pair_settled_on_cut_file",
    "cad_files_not_read",
    "bom_page_not_read_by_both",
    "detail_drawing_missing",
    "dims_required",
}

# Would a perfect engine still raise it? NO. These are confessions: something was invented,
# lost, guessed, or written where nothing can weigh it. This is the number that must fall.
_OURS = {
    "canonical_route_bom_node_disconnected",
    "bom_node_disconnected",
    "datum_written_without_source",
    "material_priced_from_a_lower_ranked_reading",
    "unpriced_line_says_why",
    "unpriced_line_says_why_not_evaluated",
    "finish_field_holds_drawing_text",
    "operation_named_but_not_priced",
    "native_top_assembly_ambiguous",
    "assembly_only_part_record",
    "nesting_rule_disagrees_with_the_cost_path",
    "price_row_identity_unjoinable",
}

# Declared assumptions with a named lever. Not a defect and not a decision — a number the
# engine chose, said so, and told you where to change. Counted apart so tuning them shows up
# as tuning rather than as either kind of failure.
_ASSUMPTIONS = {
    "powder_quantity_is_an_assumption",
    "throughput_floor_applied",
    "throughput_size_banded",
}

# A check that could not run has verified nothing. It is neither clean nor a discovery, and
# folding it into either number is how seven unverified checks came to read as a quiet job.
_UNVERIFIED_SUFFIX = "_not_evaluated"


def classify(code: Any) -> str:
    """"engine", "drawing", "assumption" or "unverified" for one violation code."""
    c = str(code or "").strip().lower()
    if not c:
        return "engine"                  # an unnamed flag is not evidence of a clean job
    if c.endswith(_UNVERIFIED_SUFFIX):
        return "unverified"
    if c in _NOT_OURS:
        return "drawing"
    if c in _ASSUMPTIONS:
        return "assumption"
    # UNKNOWN COUNTS AS OURS, DELIBERATELY. Every metric dies the same way: the inconvenient
    # thing stops being counted. A new check that nobody classified inflates the number it
    # would otherwise vanish from, which is the only pressure that keeps this table honest.
    return "engine"


def count(violations: Any) -> Dict[str, Any]:
    """The four counts for one job, and WHICH codes were ours.

    The list matters as much as the number: "three engine discoveries" is a score, and
    "bom_node_disconnected, datum_written_without_source, finish_field_holds_drawing_text" is
    a morning's work.
    """
    buckets: Dict[str, List[str]] = {"engine": [], "drawing": [],
                                     "assumption": [], "unverified": []}
    for v in violations or ():
        code = v.get("code") if isinstance(v, dict) else v
        buckets[classify(code)].append(str(code))
    return {
        "schema": SCHEMA,
        "engine_discoveries": len(buckets["engine"]),
        "drawing_and_commercial": len(buckets["drawing"]),
        "declared_assumptions": len(buckets["assumption"]),
        "unverified": len(buckets["unverified"]),
        "engine_codes": sorted(set(buckets["engine"])),
        "drawing_codes": sorted(set(buckets["drawing"])),
    }


def one_line(counted: Dict[str, Any]) -> str:
    """What a person reads at the end of a run, in the words that decide what to do next."""
    e, d = counted.get("engine_discoveries", 0), counted.get("drawing_and_commercial", 0)
    u = counted.get("unverified", 0)
    head = (f"{e} engine discovery(ies), {d} for the estimator"
            + (f", {u} check(s) could not run" if u else ""))
    if e:
        return head + " — ours: " + ", ".join(counted.get("engine_codes") or [])
    return head + " — nothing on this pack was the engine's fault"
