#!/usr/bin/env python3
"""
corpus_normalise.py — turn corpus_ingest.py output into comparable records.

Reads the corpus JSONL (a flat stream of record_type job|part|bought_in|error),
emits one comparable record per JOB (id + descriptor + metadata carrying the
totals and the commercial wrap), and prints:
  * a wrap-coverage report  — how much of the wrap the corpus actually carries
                               (tells you whether comparables can source the wrap
                               or you lean on parametric CommercialRate)
  * structured-store seed hints — per-category median bought-in value + the
                               supplier list, ready to seed CommercialRate/Supplier.

The comparable records (comparables.jsonl) are the input to the embedding step.
This script is read-only on the corpus and needs no DB / VPN / engine.

    python corpus_normalise.py --in corpus.jsonl --out comparables.jsonl
    python corpus_normalise.py --in corpus.jsonl --out comparables.jsonl --limit 20
    python corpus_normalise.py --in corpus.jsonl --out comparables.jsonl --min-raw 5
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional

WRAP_CATEGORIES = ("packaging", "pallet", "delivery", "print", "fixing", "other")


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _descriptor(job: Dict[str, Any]) -> str:
    """Prefer the corpus embedding_text; rebuild from parts if it's missing."""
    et = (job.get("embedding_text") or "").strip()
    if et:
        return et
    bits = [
        str(job.get("description") or ""),
        str(job.get("customer") or ""),
        " ".join(sorted({str(m) for m in (job.get("materials_used") or []) if m})),
        " ".join(sorted({str(d) for d in (job.get("departments_used") or []) if d})),
    ]
    return " | ".join(b for b in bits if b)


def _comparable(job: Dict[str, Any]) -> Dict[str, Any]:
    bd = job.get("bought_in_breakdown_gbp") or {}
    meta = {
        "job_no": job.get("job_no"),
        "customer": job.get("customer"),
        "description": job.get("description"),
        "year": job.get("year"),
        "quantity": _num(job.get("quantity")),
        "materials": job.get("materials_used") or [],
        "departments": job.get("departments_used") or [],
        "part_count": job.get("part_count"),
        # totals (raw is the comparable basis — pre rebate/overhead)
        "material_subtotal_gbp": _num(job.get("material_cost_gbp")),
        "labour_subtotal_gbp": _num(job.get("labour_cost_gbp")),
        "raw_total_gbp": _num(job.get("raw_manufacturing_cost_gbp")),
        "unit_cost_gbp": _num(job.get("unit_cost_gbp")),
        "sell_price_gbp": _num(job.get("sell_price_gbp")),
        "rebate_fraction": _num(job.get("rebate_fraction")),
        "overhead_divisor": _num(job.get("overhead_divisor_derived")),
        # the commercial wrap — what a sheet-less job can't see on the drawing
        "bought_in_total_gbp": _num(job.get("bought_in_total_gbp")),
        "pack_labour_gbp": _num(job.get("pack_labour_gbp")),
    }
    for cat in WRAP_CATEGORIES:
        meta[f"{cat}_gbp"] = _num(bd.get(cat))
    return {"id": str(job.get("job_no") or ""), "descriptor": _descriptor(job), "metadata": meta}


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.0f}%" if d else "—"


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalise corpus.jsonl into comparable records.")
    ap.add_argument("--in", dest="inp", default="corpus.jsonl", help="corpus JSONL from corpus_ingest")
    ap.add_argument("--out", default="comparables.jsonl", help="output comparable records")
    ap.add_argument("--limit", type=int, default=None, help="cap jobs emitted (dry run)")
    ap.add_argument("--min-raw", type=float, default=None,
                    help="skip jobs whose raw_total_gbp is below this (junk filter)")
    args = ap.parse_args()

    jobs: List[Dict[str, Any]] = []
    bought_in: List[Dict[str, Any]] = []
    n_lines = n_bad = n_err = 0
    with open(args.inp, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                n_bad += 1
                continue
            rt = rec.get("record_type")
            if rt == "job":
                jobs.append(rec)
            elif rt == "bought_in":
                bought_in.append(rec)
            elif rt == "error":
                n_err += 1

    # filter + emit
    emitted = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for job in jobs:
            raw = _num(job.get("raw_manufacturing_cost_gbp"))
            if args.min_raw is not None and (raw is None or raw < args.min_raw):
                continue
            out.write(json.dumps(_comparable(job), ensure_ascii=False) + "\n")
            emitted += 1
            if args.limit and emitted >= args.limit:
                break

    # ---- wrap-coverage report ---------------------------------------------------------
    def _has(key: str) -> int:
        return sum(1 for j in jobs if _num(j.get(key)))

    def _has_wrap(cat: str) -> int:
        return sum(1 for j in jobs if _num((j.get("bought_in_breakdown_gbp") or {}).get(cat)))

    nj = len(jobs)
    years = sorted({j.get("year") for j in jobs if j.get("year")})
    print(f"\nRead {n_lines} lines -> {nj} jobs, {len(bought_in)} bought-in, "
          f"{n_err} ingest errors, {n_bad} unparseable. Emitted {emitted} comparables -> {args.out}")
    if years:
        print(f"Year span: {years[0]}–{years[-1]}")
    if not nj:
        print("No job records found — check the corpus path / that ingest produced jobs.")
        return

    print("\nWrap coverage (jobs with a non-zero value) — the no-sheet sourcing question:")
    print(f"  raw total        {_has('raw_manufacturing_cost_gbp'):>4} / {nj}  ({_pct(_has('raw_manufacturing_cost_gbp'), nj)})")
    print(f"  bought-in total  {_has('bought_in_total_gbp'):>4} / {nj}  ({_pct(_has('bought_in_total_gbp'), nj)})")
    print(f"  pack labour      {_has('pack_labour_gbp'):>4} / {nj}  ({_pct(_has('pack_labour_gbp'), nj)})")
    for cat in WRAP_CATEGORIES:
        print(f"    {cat:<13} {_has_wrap(cat):>4} / {nj}  ({_pct(_has_wrap(cat), nj)})")

    # ---- structured-store seed hints --------------------------------------------------
    if bought_in:
        by_cat: Dict[str, List[float]] = defaultdict(list)
        suppliers: Dict[str, str] = {}
        for b in bought_in:
            v = _num(b.get("extended_value_gbp")) or _num(b.get("unit_price_gbp"))
            if v:
                by_cat[b.get("category") or "other"].append(v)
            sup = (b.get("supplier") or "").strip()
            if sup:
                suppliers[sup.lower()] = sup
        print("\nStructured-store seed hints (per-category bought-in £, from real lines):")
        print(f"  {'category':<13}{'n':>5}{'median':>10}{'mean':>10}{'max':>10}")
        for cat in WRAP_CATEGORIES:
            vals = by_cat.get(cat) or []
            if vals:
                print(f"  {cat:<13}{len(vals):>5}{statistics.median(vals):>10.2f}"
                      f"{statistics.fmean(vals):>10.2f}{max(vals):>10.2f}")
        if suppliers:
            print(f"\n  Distinct suppliers seen ({len(suppliers)}): "
                  + ", ".join(sorted(suppliers.values()))[:300])
    else:
        print("\nNo bought-in records in corpus — re-run corpus_ingest with the wrap patch "
              "so the commercial-wrap detail is carried (else comparables have totals only).")


if __name__ == "__main__":
    main()
