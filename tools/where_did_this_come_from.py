r"""Every attributed field on one part, with its source and its rank — in every pool.

"Do we know where each item came from?" is answerable only against a record. This prints
one, field by field, and prints it from EACH of the three pools a part lives in, because
the interesting failure is not a missing source but two records giving different ones.

That failure is live: on job 12392 the raw part says its material came from solidworks_api
and the writeup part says drawing_deterministic. Same value, two provenance claims, because
the two records never met and precedence therefore never arbitrated between rank 90 and
rank 70.

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
    from source_precedence import rank as _rank
except Exception:                                                  # pragma: no cover
    def _rank(_s):
        return 0


def _pools(doc):
    """The three places one part lives, named as an estimator would ask for them."""
    return (
        ("raw part record", doc.get("parts") or []),
        ("manufacturing write-up", (doc.get("manufacturing_writeup") or {}).get("parts") or []),
        ("costed part estimate",
         (doc.get("estimate_summary") or {}).get("part_estimates") or []),
    )


def _attributed(record, prefix=""):
    """(field, value, source) for every field in this record that records a source.

    Walks nested records, because the fields that drive cost mostly do not live at the top
    of a part — geometry_rollup and normalized_geometry both carry their own stamps.
    """
    out = []
    if not isinstance(record, dict):
        return out
    for key, value in record.items():
        if key.endswith("_source") or key.endswith("_confidence"):
            continue
        src = record.get(f"{key}_source")
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
    for label, pool in _pools(doc):
        rec = next((r for r in pool if isinstance(r, dict)
                    and str(r.get("part_number") or "").strip().upper() == code), None)
        print(f"--- {label} ---")
        if rec is None:
            print("    ABSENT from this pool\n")
            continue
        fields = _attributed(rec)
        if not fields:
            print("    no attributed field on this record\n")
        for field, value, src in sorted(fields):
            print(f"    {field:34} {str(value)[:26]:28} <- {src} (rank {_rank(src)})")
            seen.setdefault(field, {})[label] = src
        print()

    # THE DISAGREEMENTS ARE THE POINT. A field with one source everywhere is settled; a
    # field with two is a question nobody has answered, and the deliverables read only one
    # of the records.
    print("--- fields whose source depends on which record you ask ---")
    _split = {f: v for f, v in seen.items() if len(set(v.values())) > 1}
    if not _split:
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
