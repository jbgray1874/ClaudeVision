"""Freeze an accepted run into tests/replay/<job>/ — slimmed, but only provably so.

RUN THIS ON THE BOX. It turns an accepted output/json/<job>.json into the two files the replay
gate needs, and it keeps the fixture small enough that committing one per pack is not a
permanent cost to the repository:

    python tools\\freeze_replay_fixture.py 7332-01 ^
        --accepted-run "the 14:17 pack, 7 Sep" ^
        --accepted-by "J Gray" --accepted-on 2026-09-07 ^
        --unit 80.09 --material 40.89 --labour 33.59 --quantity 6

WHY A SLIMMED FIXTURE IS SAFE HERE, AND HOW THAT IS ESTABLISHED RATHER THAN ASSUMED. Most of a
saved record's weight is extracted page text — on a 25-page pack that is the whole drawing set
transcribed, and none of it is read by the three replay tiers. But "none of it is read" is
exactly the sort of claim that is true until somebody adds a reader, and a fixture quietly
missing a field the gate needs would weaken the gate while still reporting green: the failure
mode this whole harness exists to prevent.

So nothing is dropped on the strength of that reasoning. The tool computes a STRUCTURAL
FINGERPRINT by running the same reads all three tiers run — the costed lines, the outstanding
tally, the workbook canonicalisation, the compiled route decisions and the re-costed material
figures — first against the complete record, then against each candidate reduction. A
reduction is accepted ONLY if its fingerprint is byte-identical to the full record's. If no
reduction verifies, the full record is written and the tool says so plainly. A smaller file is
worth having; it is not worth a gate that has stopped gating.

The fingerprint is written beside the fixture as fingerprint.json, so the next freeze of the
same pack can show what moved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPLAY = ROOT / "tests" / "replay"

# Keys whose only content is transcribed source text or per-page model output. Candidates for
# removal — never removed without the fingerprint agreeing.
PAGE_TEXT_KEYS = ("text", "raw_text", "page_text", "full_text", "content",
                  "ocr_text", "extracted_text")


def _num(value: Any) -> Optional[float]:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _fingerprint(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the three replay tiers actually assert on, in one comparable structure.

    Deliberately derived by CALLING the same code the tiers call, not by copying fields: a
    fingerprint assembled from a hand-written field list would miss exactly the field somebody
    added a reader for, which is the failure this guards against.
    """
    out: Dict[str, Any] = {}

    # tier 1 — the costed record and the shared tally
    import costed_facts as cf
    record = cf.costed_job(copy.deepcopy(summary))
    lines = [l for l in (record.get("lines") or []) if isinstance(l, dict)]
    out["lines"] = sorted(
        [{"part_number": str(l.get("part_number") or "").upper(),
          "qty_per_unit": _num(l.get("qty_per_unit")),
          "kind": str(l.get("kind") or ""),
          "operations": sorted(str(o).lower() for o in (l.get("operations") or [])),
          "charged_unit_gbp": _num(l.get("charged_unit_gbp")),
          "engine_unit_gbp": _num(l.get("engine_unit_gbp")),
          "price_firmness": str((l.get("price_origin") or {}).get("firmness") or ""),
          } for l in lines],
        key=lambda r: r["part_number"])
    tally = cf.outstanding_summary(copy.deepcopy(summary)) or {}
    out["tally"] = {k: tally.get(k) for k in sorted(tally)
                    if isinstance(tally.get(k), (int, float, str, type(None)))}
    out["removed_identities"] = sorted(str(x).upper() for x in cf.removed_identities(summary))
    out["canonical_nodes"] = sorted(str(x).upper() for x in cf._canonical_nodes(summary))

    # tier 2 — the workbook canonicalisation stage
    raw = [p for p in ((summary.get("estimate_summary") or {}).get("part_estimates") or [])
           if isinstance(p, dict)]
    try:
        import wb_populate
        canon = wb_populate.canonicalise_part_estimates_for_workbook(
            copy.deepcopy(summary), copy.deepcopy(raw))
        out["canonicalised"] = sorted({str(p.get("part_number") or "").strip().upper()
                                       for p in canon if isinstance(p, dict)} - {""})
    except Exception as err:                                             # noqa: BLE001
        out["canonicalised"] = f"ERROR {type(err).__name__}: {err}"

    # tier 3 — routing re-derived, and material re-costed
    try:
        import route_compiler
        doc = summary.get("document_analysis") or {}
        compiled = route_compiler.compile_job_route(
            copy.deepcopy(raw),
            llm_extract=summary.get("llm_extract") or {},
            bom_rows=doc.get("bom_rows") or [])
        out["route_decisions"] = sorted(
            f"{str(d.get('part_number') or d.get('target_id') or '').upper()}"
            f"|{str(d.get('operation') or '').lower()}"
            f"|{str(d.get('status') or '').lower()}"
            for d in (compiled.get("decisions") or []) if isinstance(d, dict))
    except Exception as err:                                             # noqa: BLE001
        out["route_decisions"] = f"ERROR {type(err).__name__}: {err}"

    try:
        import estimator
        costs = {}
        for part in raw:
            pn = str(part.get("part_number") or "").upper()
            if not pn:
                continue
            try:
                fresh = estimator.estimate_material(copy.deepcopy(part)) or {}
                costs[pn] = _num(fresh.get("unit_material_cost_gbp"))
            except Exception as err:                                     # noqa: BLE001
                costs[pn] = f"ERROR {type(err).__name__}"
        out["material_recosted"] = {k: costs[k] for k in sorted(costs)}
    except Exception as err:                                             # noqa: BLE001
        out["material_recosted"] = f"ERROR {type(err).__name__}: {err}"

    return out


def _digest(fingerprint: Dict[str, Any]) -> str:
    blob = json.dumps(fingerprint, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── the candidate reductions, smallest saving first ───────────────────────────────────


def _drop_page_text(summary: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Transcribed page text. Usually the bulk of the file by a wide margin."""
    out = copy.deepcopy(summary)
    dropped: List[str] = []
    for page in (out.get("pages") or []):
        if not isinstance(page, dict):
            continue
        for key in PAGE_TEXT_KEYS:
            if key in page and isinstance(page[key], str) and len(page[key]) > 200:
                dropped.append(f"pages[].{key}")
                page[key] = ""
    return out, sorted(set(dropped))


def _drop_page_analysis_detail(summary: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Per-page model output below the page level — kept only where a tier reads it."""
    out, dropped = _drop_page_text(summary)
    for page in (out.get("pages") or []):
        if not isinstance(page, dict):
            continue
        analysis = page.get("page_analysis")
        if isinstance(analysis, dict):
            for key in list(analysis):
                value = analysis[key]
                if isinstance(value, str) and len(value) > 500:
                    dropped.append(f"pages[].page_analysis.{key}")
                    analysis[key] = ""
    return out, sorted(set(dropped))


REDUCTIONS = (
    ("page text", _drop_page_text),
    ("page text + long page-analysis strings", _drop_page_analysis_detail),
)


def freeze(job: str, source: Path, provenance: Dict[str, Any],
           force_full: bool = False) -> int:
    target_dir = REPLAY / job
    if not target_dir.is_dir():
        print(f"!! {target_dir} does not exist — is '{job}' the right job name?")
        return 2
    if not (target_dir / "accepted_facts.json").is_file():
        print(f"!! {target_dir}/accepted_facts.json is missing. The accepted STRUCTURE is an "
              f"estimator-reviewed file and this tool will not invent one.")
        return 2

    full = json.loads(source.read_text(encoding="utf-8"))
    full_bytes = len(json.dumps(full).encode("utf-8"))
    print(f"   source: {source}  ({full_bytes / 1_048_576:.1f} MB)")

    print("   computing the structural fingerprint of the complete record ...")
    base = _fingerprint(full)
    base_digest = _digest(base)
    print(f"   fingerprint {base_digest[:16]}  "
          f"({len(base.get('lines') or [])} costed lines, "
          f"{len(base.get('route_decisions') or [])} route decisions)")
    for key in ("canonicalised", "route_decisions", "material_recosted"):
        if isinstance(base.get(key), str) and base[key].startswith("ERROR"):
            print(f"   !! tier reading '{key}' errored on the FULL record: {base[key]}")
            print(f"      Freezing anyway — the fixture is honest about what the code does "
                   "today — but expect that tier to fail until it is fixed.")

    chosen, chosen_name, chosen_dropped = full, "nothing (full record)", []
    if not force_full:
        for name, reduce in REDUCTIONS:
            candidate, dropped = reduce(full)
            if not dropped:
                continue
            size = len(json.dumps(candidate).encode("utf-8"))
            same = _digest(_fingerprint(candidate)) == base_digest
            verdict = "identical" if same else "DIFFERENT — rejected"
            print(f"   try: drop {name:40s} -> {size / 1_048_576:5.1f} MB  {verdict}")
            if same and size < len(json.dumps(chosen).encode("utf-8")):
                chosen, chosen_name, chosen_dropped = candidate, name, dropped

    summary_path = target_dir / "summary.json"
    summary_path.write_text(json.dumps(chosen, indent=1, sort_keys=True), encoding="utf-8")
    final_bytes = summary_path.stat().st_size
    print(f"   wrote {summary_path}  ({final_bytes / 1_048_576:.1f} MB, "
          f"dropped: {chosen_name})")

    provenance = dict(provenance)
    provenance["job"] = job
    provenance["source_path"] = str(source)
    provenance["fixture"] = {
        "dropped": chosen_dropped,
        "reduction": chosen_name,
        "full_record_bytes": full_bytes,
        "fixture_bytes": final_bytes,
        "structural_fingerprint": base_digest,
        "_note": ("The reduction was accepted only because the structural fingerprint of the "
                  "reduced record is byte-identical to the complete record's. Nothing was "
                  "dropped on the reasoning that it 'is not read'."),
    }
    (target_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"   wrote {target_dir / 'provenance.json'}")
    (target_dir / "fingerprint.json").write_text(
        json.dumps(base, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"   wrote {target_dir / 'fingerprint.json'}  (what the next freeze is compared to)")

    print()
    print("   Now, from the repository root:")
    print(f"       git add tests/replay/{job}")
    print(f'       git commit -m "Freeze the accepted {job} record"')
    print("       git push -u origin main-2026")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", help="the job name, matching the tests/replay/<job> directory")
    ap.add_argument("--source", default="",
                    help="path to the accepted record (default output/json/<job>.json)")
    ap.add_argument("--accepted-run", required=True,
                    help='which run this is, e.g. "the 14:17 pack, 7 Sep"')
    ap.add_argument("--accepted-by", required=True, help="who signed it off")
    ap.add_argument("--accepted-on", required=True, help="YYYY-MM-DD")
    ap.add_argument("--unit", type=float, default=None, help="accepted unit price")
    ap.add_argument("--material", type=float, default=None, help="accepted material")
    ap.add_argument("--labour", type=float, default=None, help="accepted labour")
    ap.add_argument("--quantity", type=int, default=None, help="quantity it was settled at")
    ap.add_argument("--notes", default="", help="anything a reader would have to ask")
    ap.add_argument("--full", action="store_true",
                    help="skip every reduction and freeze the complete record")
    args = ap.parse_args(argv)

    source = Path(args.source) if args.source else (ROOT / "output" / "json" / f"{args.job}.json")
    if not source.is_file():
        print(f"!! {source} not found. Pass --source with the path to the accepted record.")
        return 2

    provenance: Dict[str, Any] = {
        "accepted_run": args.accepted_run,
        "accepted_by": args.accepted_by,
        "accepted_on": args.accepted_on,
        "notes": args.notes,
    }
    money = {k: v for k, v in (("unit_gbp", args.unit), ("material_gbp", args.material),
                               ("labour_gbp", args.labour), ("quantity", args.quantity))
             if v is not None}
    if money:
        money["_note"] = ("Recorded for the Windows Excel/read-back reconciliation ONLY. The "
                          "fast replay layer pins structure and never money.")
        provenance["accepted_numbers"] = money

    print(f"== freezing {args.job} ==")
    return freeze(args.job, source, provenance, force_full=bool(args.full))


if __name__ == "__main__":
    raise SystemExit(main())
