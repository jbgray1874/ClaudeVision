r"""Every attributed field on one part, with its source and its rank — in every pool.

"Do we know where each item came from?" is answerable only against a record. This prints
one, field by field, and prints it from EACH of the three pools a part lives in, because
the interesting failure is not a missing source but two records giving different ones.

A CORRECTION, because this file used to assert the opposite. It said the failure was live —
that on job 12392 the raw part claimed solidworks_api and the writeup part claimed
drawing_deterministic, two provenance claims for one value. That was a hypothesis from
reading two writers in two files, and tracing the pipeline disproved it. In a single run
the three pools are three NAMES for one set of dicts: file_scan assigns
summary["parts"] = manufacturing_writeup["parts"], and estimate_part mutates its argument
and returns it, so a part_estimate IS the writeup record. The two material writes do meet,
and rank 90 beats rank 70 exactly as it should.

So this tool prints three blocks that are usually identical, and that is the answer, not a
gap in the instrument. It says so below rather than letting three matching blocks be read
as arbitration that never had to happen.

The divergence that IS real between the pools is membership, not provenance: part_estimates
holds only the parts that passed the estimable filter, so a part can be fully attributed and
still absent from the costed pool. That is the shape of the bought-in disconnects on 12392,
and ABSENT is reported below as its own outcome for that reason.

Where two readings of one line genuinely do exist — Path A and Path B on a BOM row, two
drawings printing the same fastener, a parts list continued on a second sheet — they are
merged field by field by src/record_merge.py before any part record is built, and what the
merge did is recorded in `merge_notes` on the row.

    C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\tools\where_did_this_come_from.py 12392-02-01M
    ...\where_did_this_come_from.py 12392-02-01M --job 12392
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from source_precedence import rank as _rank, _SOURCE_FIELDS
except Exception:                                                  # pragma: no cover
    def _rank(_s):
        return 0
    _SOURCE_FIELDS = {}


def _pools(doc):
    """The three places one part lives, named as an estimator would ask for them."""
    return (
        ("raw part record", doc.get("parts") or []),
        ("manufacturing write-up", (doc.get("manufacturing_writeup") or {}).get("parts") or []),
        ("costed part estimate",
         (doc.get("estimate_summary") or {}).get("part_estimates") or []),
    )


# WHERE A DECISION WAS TAKEN, named by the module that owns the ranks — never a private
# copy here. A provenance report that cannot name a source cannot explain a decision.
try:
    from source_precedence import display_name as _display, was_measured as _was_measured
except Exception:                                                   # pragma: no cover
    def _display(s):
        return str(s or "").replace("_", " ")

    def _was_measured(s):
        return bool(s) and str(s) not in ("llm_extract", "llm_full_extract",
                                          "inference", "geometry_inference")


def _attributed(record, prefix=""):
    """(field, value, source) for every field in this record that records a source.

    Walks nested records, because the fields that drive cost mostly do not live at the top
    of a part — geometry_rollup and normalized_geometry both carry their own stamps.

    Where a field's stamp lives is asked of source_precedence, not assumed. Three fields
    do not follow the <field>_source convention — normalized_material is stamped in
    material_source, quantity in quantity_source, normalized_thickness_mm in
    thickness_source — and a tool that only knows the convention silently omits them.
    Material is the field this whole question was asked about, so omitting it made the
    instrument answer "nothing to see" about the one datum in dispute.
    """
    out = []
    if not isinstance(record, dict):
        return out
    _stamps = set(_SOURCE_FIELDS.values())
    for key, value in record.items():
        if key in _stamps or key.endswith("_source") or key.endswith("_confidence"):
            continue
        src = record.get(_SOURCE_FIELDS.get(key, f"{key}_source"))
        if src:
            out.append((prefix + key, value, src))
        if isinstance(value, dict):
            out.extend(_attributed(value, prefix + key + "."))
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    code = args[0].strip().upper()
    job = args[1] if len(args) > 1 else ""

    root = Path(__file__).resolve().parents[1] / "output" / "json"
    hits = glob.glob(str(root / f"*{job}*.json")) if job else glob.glob(str(root / "*.json"))
    if not hits:
        print("no scan JSON found")
        return 2
    path = max(hits, key=os.path.getmtime)
    doc = json.load(open(path, encoding="utf-8"))
    print(f"reading {os.path.basename(path)}\n{code}\n")

    seen = {}
    absent = []
    ids = {}
    for label, pool in _pools(doc):
        rec = next((r for r in pool if isinstance(r, dict)
                    and str(r.get("part_number") or "").strip().upper() == code), None)
        print(f"--- {label} ---")
        if rec is None:
            # NOT A MISSING SOURCE — A MISSING PART. A record can be perfectly attributed
            # and still never reach the costed pool, and that reads as silence in every
            # report that only walks part_estimates.
            absent.append(label)
            print("    ABSENT from this pool\n")
            continue
        # NOT id(). Serialisation has already destroyed the aliasing — json.load builds a
        # fresh dict per pool whether or not the writer held one object — so identity is
        # unanswerable here and a byte-identical record is the closest true signal.
        ids[label] = json.dumps(rec, sort_keys=True, default=str)
        fields = _attributed(rec)
        if not fields:
            print("    no attributed field on this record\n")
        for field, value, src in sorted(fields):
            # WHERE THE DECISION WAS TAKEN, in the estimator's words as well as the join
            # key. This printed the raw key alone, so a report written to answer "where did
            # this come from" answered "solidworks_flat_pattern" — correct, and not an
            # answer anybody outside this codebase can read. The name comes from the module
            # that owns the ranks, so a name and a rank cannot disagree about a source.
            _mark = "measured" if _was_measured(src) else "reasoned"
            print(f"    {field:34} {str(value)[:26]:28} <- {_display(src)} "
                  f"[{src}, rank {_rank(src)}, {_mark}]")
            seen.setdefault(field, {})[label] = src
        print()

    # WHAT THE MERGE DID, where two readings of this line existed at all. Written by
    # src/record_merge.py onto the surviving row: every gap one reading filled for the
    # other, and every field where they disagreed. A row with no notes was read once.
    _notes = []
    for _label, _pool in _pools(doc):
        _rec = next((r for r in _pool if isinstance(r, dict)
                     and str(r.get("part_number") or "").strip().upper() == code), None)
        for _n in ((_rec or {}).get("merge_notes") or []):
            if _n not in _notes:
                _notes.append(_n)
    print("--- what the merge did when two readings described this line ---")
    if not _notes:
        print("    nothing recorded — one reading of this line, or no reader ran twice")
    for _n in _notes:
        print(f"    {_n}")
    print()

    if absent:
        print("--- pools this part never reached ---")
        for _a in absent:
            print(f"    {_a}")
        print("    A part absent from the costed pool is not costed. No amount of "
              "provenance on the record it DOES have changes that.\n")

    # THE DISAGREEMENTS ARE THE POINT. A field with one source everywhere is settled; a
    # field with two is a question nobody has answered, and the deliverables read only one
    # of the records.
    print("--- fields whose source depends on which record you ask ---")
    _split = {f: v for f, v in seen.items() if len(set(v.values())) > 1}
    if not _split:
        # SAY WHY THEY AGREE. "Every field agrees" reads as arbitration that worked; when
        # the pools hold the SAME dict it means no arbitration was ever required, and the
        # two claims are not independent confirmations of each other.
        if len(set(ids.values())) <= 1 and len(ids) > 1:
            print("    none — and these records are byte-identical, which is what one "
                  "record written to three places looks like. The pools are not three "
                  "independent readings agreeing; they are one reading, printed thrice")
        else:
            print("    none — every attributed field agrees across the pools it appears in")
    for field, byplace in sorted(_split.items()):
        best = max(byplace.values(), key=_rank)
        print(f"    {field}")
        for place, src in byplace.items():
            mark = "  <- outranks" if src == best and _rank(src) > 0 else ""
            print(f"        {place:26} {src} (rank {_rank(src)}){mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
