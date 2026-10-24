"""A saved run record, cut to what a review of it needs — small enough to attach (D-596).

    python tools/evidence_digest.py --record output/json/<job>.json [--out <folder>]

A run record carries every page's text, every reader's raw answer and every intermediate
pass, and runs to many megabytes. Checking a book against its read needs a fraction of it:
the read as kept (its key, its hash and length, not its words), the read ledger and its
final states, the engine's allowances, the calculated workbook rows and totals, the quantity
sweep, the parts as costed, the consistency findings and the release. That is what this
writes, to <out>/<job>_digest.json (default output/replay), and prints a short account.

Read-only: the record is not changed. The digest is private job data like the record it is
cut from — internal, never published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PART_KEYS = ("part_number", "description", "quantity", "normalized_material",
              "normalized_thickness_mm", "concept_kind", "read_origin", "set_aside",
              "weld_charged_on", "coat_charged_on", "normalized_finish",
              "weld_process_stated", "_plating_members", "_plating_weldment")


def digest(record: dict) -> dict:
    """The parts of a run record a review needs. Pure."""
    cr = record.get("concept_read") if isinstance(record.get("concept_read"), dict) else {}
    raw = str(cr.get("raw_response") or "")
    es = record.get("estimate_summary") if isinstance(record.get("estimate_summary"), dict) else {}
    ests = es.get("canonical_part_estimates") or es.get("part_estimates") or []
    parts = []
    for p in ests:
        if not isinstance(p, dict):
            continue
        pe = p.get("process_estimate") if isinstance(p.get("process_estimate"), dict) else {}
        me = p.get("material_estimate") if isinstance(p.get("material_estimate"), dict) else {}
        parts.append(dict({k: p.get(k) for k in _PART_KEYS if k in p},
                          run_minutes_per_piece=pe.get("run_times_min_per_unit"),
                          setup_minutes=pe.get("setup_times_min"),
                          material_method=me.get("cost_method"),
                          unit_material_gbp=me.get("unit_material_cost_gbp")))
    inv = record.get("invariants") if isinstance(record.get("invariants"), dict) else {}
    cj = record.get("costed_job") if isinstance(record.get("costed_job"), dict) else {}
    ledger = record.get("read_ledger") if isinstance(record.get("read_ledger"), dict) else {}
    return {
        "schema": "evidence_digest.v1",
        "job": record.get("job_output_stem") or record.get("declared_product"),
        "engine_build": (es.get("engine_build") or record.get("engine_build")
                         or record.get("commit")),
        "llm_only": record.get("llm_only"),
        "requested_order_quantity": record.get("requested_order_quantity"),
        "concept_read": dict({k: v for k, v in cr.items() if k != "raw_response"},
                             raw_chars=len(raw),
                             raw_sha256=(hashlib.sha256(raw.encode("utf-8")).hexdigest()
                                         if raw else "")),
        "read_ledger": ledger,
        "read_charge_result": record.get("read_charge_result"),
        "final_estimate": record.get("final_estimate"),
        "workbook_labour": record.get("workbook_labour"),
        "quantity_sweep": {k: v for k, v in (record.get("quantity_sweep") or {}).items()
                           if k in ("rows", "baseline_quantity", "order_qty_cell")}
        if isinstance(record.get("quantity_sweep"), dict) else None,
        "parts": parts,
        "estimator_decisions": record.get("estimator_decisions"),
        "invariants": {"may_quote_firm": inv.get("may_quote_firm"),
                       "violations": [{k: v.get(k) for k in ("code", "severity", "message")}
                                      for v in (inv.get("violations") or [])
                                      if isinstance(v, dict)]},
        "release": cj.get("release"),
        "decisions_required": cj.get("decisions_required"),
        "review_flags": list(record.get("review_flags") or [])[:200],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", required=True, help="the saved run record (output/json/<job>.json)")
    ap.add_argument("--out", help="folder for the digest (default output/replay)")
    args = ap.parse_args(argv)
    path = Path(args.record)
    record = json.loads(path.read_text(encoding="utf-8"))
    d = digest(record)
    out_dir = Path(args.out) if args.out else ROOT / "output" / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{path.stem}_digest.json"
    out.write_text(json.dumps(d, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    rc = d.get("read_charge_result") or {}
    counts = rc.get("counts") or {}
    print(f"Record {path.name}: {path.stat().st_size / 1e6:.1f} MB -> digest "
          f"{out.stat().st_size / 1e3:.0f} kB at {out}")
    print(f"  read: {d['concept_read'].get('raw_chars')} chars, key "
          f"{d['concept_read'].get('read_key') or '-'}, replayed from "
          f"{d['concept_read'].get('replayed_from') or '-'}")
    print(f"  ledger: {len((d.get('read_ledger') or {}).get('items') or [])} item(s); "
          f"result {counts or 'not run'}; passed {rc.get('passed')}")
    print(f"  calculated workbook: {'yes' if (d.get('final_estimate') or {}).get('source') == 'excel_calculated' else 'NO'}; "
          f"release {((d.get('release') or {}).get('status'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
