"""PRE-FLIGHT: will the next run charge a bend on every tube it bends — and price every tube
from a length that is a length?

Answers, in seconds and without running the estimate, two questions that cost a morning to
answer the slow way:

  1. Does the route compiler raise a REQUIRED bending operation for every part whose stock
     form is a tube?  7332-01's leg was correctly told it cannot go through a press brake (a
     tube has no flat blank), the flat-sheet 'folding' claim was ruled not_applicable — and
     nothing raised the operation that IS possible, so under the canonical cutover, where a
     labour row exists only where a REQUIRED decision does, the bend left the sheet entirely
     and the leg was bent for free. £8.70 of Tubebend, gone between two runs, silently.

  2. Where did each tube's LENGTH come from?  Section is priced per metre, so the length is
     the money. The estimator stamps the rung (section_stock / stated_length / ... /
     max_dimension_fallback) and the reader (llm_full_extract, weldment_cut_list, ...) on
     every priced section line. This prints them, and FAILS if a tube is priced from the
     fallback and the figure is a cut-path total (7332's 9,106 mm page sum) or longer than
     any bar of stock — a number that is not a length, priced as one. A fallback that is
     merely unconfirmed (a stand's height standing in for its leg) is printed as INDICATIVE
     and does not fail: the line carries the flag, and Tim confirms the height off the GA.

Usage (from the engine root):
    python tools\\preflight_tube_bend.py                       # newest job JSON in output/json
    python tools\\preflight_tube_bend.py path\\to\\7332-01.json

Exit code 0 = every tube keeps a bend and every priced tube length is a length (or there are
no tubes). 1 = a tube would be bent free, or priced from a figure that is not a length.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

BEND_OPS = {"fold", "folding", "linebend", "line_bend", "tubebend", "tube_bending"}


# Files that live beside a job's outputs and are NOT the job: the whole-document LLM extract
# (rows carry tube_section / cut_length_mm, never section_stock), parity bundles, priced
# re-exports. On 7332 the newest .json under output/ was the extract sidecar, and the
# pre-flight answered "no tube parts on this job" about a file that was never the job.
_SIDECAR_SUFFIXES = ("_llm_extract.json", "_parity_bundle.json", ".priced_estimate.json",
                     ".workbook_parity.json", ".estimate_parity.json", ".formula_parse.json",
                     ".historical_job_record.json")


def _looks_like_a_job(doc: Any) -> bool:
    """A saved job document: part RECORDS (the shape estimate_part costs), not an extract."""
    if not isinstance(doc, dict):
        return False
    if str(doc.get("source") or "") in ("llm_full_extract", "llm_full_extract_inference"):
        return False
    parts = (doc.get("parts") or (doc.get("scan") or {}).get("parts")
             or doc.get("part_records") or [])
    return any(isinstance(p, dict) and p.get("part_number") for p in parts)


def _newest_job_json() -> str:
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    hits = []
    for pat in ("output/json/*.json", "output/estimates/*.json", "output/*.json"):
        hits.extend(glob.glob(os.path.join(here, pat)))
    hits = [h for h in hits if not h.lower().endswith(_SIDECAR_SUFFIXES)]
    if not hits:
        sys.exit("no job JSON found under output/ — pass one as an argument")
    # Newest first, but the newest file that IS a job: a stray sidecar with an unlisted
    # suffix is skipped by shape, and the skip is printed so nobody trusts a silent choice.
    for path in sorted(hits, key=os.path.getmtime, reverse=True):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:                                              # noqa: BLE001
            continue
        if _looks_like_a_job(doc):
            return path
        print(f"  (skipped {os.path.basename(path)} — not a job document)")
    sys.exit("no JSON under output/ holds part records — pass the job JSON as an argument")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else _newest_job_json()
    print(f"job JSON : {path}")
    with open(path, encoding="utf-8") as fh:
        summary = json.load(fh)

    if not _looks_like_a_job(summary):
        sys.exit("that file is not a job document — an LLM extract sidecar or a parity "
                 "bundle, not the saved job. Pass the job JSON (output\\json\\<job>.json).")
    parts = (summary.get("parts")
             or (summary.get("scan") or {}).get("parts")
             or summary.get("part_records") or [])
    if not parts:
        sys.exit("no parts in that JSON — is it a scan/final_estimate document?")

    import blank_credibility as bc
    import estimator as e
    import route_compiler as rc

    # ONLY THE CANDIDATES. Costing every part ran estimate_part across the whole job — minutes
    # on a box with a live pricing service, and the verdict never printed. A part can only be a
    # tube if it already carries a section profile, says so in its description, or has been
    # tagged; nothing else can change into one, so nothing else needs costing to find out.
    def _candidate(p) -> bool:
        if not isinstance(p, dict):
            return False
        if p.get("section_stock") or str(p.get("stock_form") or "").lower() in (
                "tube", "section"):
            return True
        blob = f"{p.get('description') or ''} {p.get('normalized_material') or ''}".upper()
        return any(w in blob for w in ("TUBE", "CHS", "RHS", "SHS", "BOX SECTION"))

    cands = [p for p in parts if _candidate(p)]
    print(f"parts: {len(parts)}   tube candidates to cost: {len(cands)}", flush=True)
    qty = int(summary.get("assumed_job_quantity") or 1)
    costed: Dict[str, Dict[str, Any]] = {}
    for p in cands:
        print(f"  costing {p.get('part_number')} ...", flush=True)
        try:
            costed[str(p.get("part_number"))] = e.estimate_part(p, job_quantity=qty) or {}
        except Exception as exc:                                       # noqa: BLE001
            print(f"  ! {p.get('part_number')}: estimate_part skipped ({exc})", flush=True)

    tubes = [p for p in parts
             if isinstance(p, dict) and str(p.get("stock_form") or "").lower() == "tube"]
    if not tubes:
        print("\nno tube parts on this job — nothing to check.")
        return 0

    # ── 2. the length each tube is priced from ─────────────────────────────────────
    envelope = bc.stated_job_envelope_mm(summary)
    print(f"\ntube parts: {len(tubes)}   job envelope stated: "
          f"{f'{envelope:,.0f} mm' if envelope else 'none'}", flush=True)
    bad_lengths = []
    for p in tubes:
        pn = str(p.get("part_number"))
        pe = costed.get(pn) or {}
        me = pe.get("material_estimate") if isinstance(pe.get("material_estimate"), dict) else {}
        if not me:
            me = p.get("material_estimate") if isinstance(p.get("material_estimate"), dict) else {}
        se = me.get("stock_estimate") if isinstance(me.get("stock_estimate"), dict) else {}
        length = _num(se.get("section_length_mm"))
        price = _num(me.get("unit_material_cost_gbp"))
        src = str(se.get("section_length_source") or p.get("_section_length_source") or "?")
        reader = str(se.get("section_length_reader") or p.get("_section_length_reader") or "?")
        print(f"\n  {pn}  ({p.get('description') or ''})")
        print(f"      length {f'{length:,.0f} mm' if length else 'NONE':>12s}   "
              f"source {src}   read by {reader}   "
              f"unit material {f'GBP {price:.2f}' if price else 'UNPRICED'}")
        if not price:
            print("      (unpriced — the line carries its reason; nothing to judge here)")
            continue
        if src == e.SECTION_LENGTH_FALLBACK:
            absurd = bc.section_length_is_absurd(p, length)
            if absurd:
                bad_lengths.append(pn)
                print(f"      ^^ PRICED FROM A FIGURE THAT IS NOT A LENGTH — it {absurd}")
                continue
            over = bc.section_length_is_absurd(p, length, envelope_mm=envelope)
            print("      INDICATIVE: length is the fallback (largest dimension on the part), "
                  "flagged on the line — confirm the height off the GA"
                  + (f"\n      NOTE: that figure {over}" if over else ""))
        else:
            hit = bc.section_length_matches_a_cut_path(p, length)
            if hit:
                print(f"      NOTE: a stated length that equals {hit} — check the transcription")

    # ── 1. the bend ────────────────────────────────────────────────────────────────
    graph = rc.compile_job_route(parts, summary.get("llm_full_extract") or {})
    by_part: dict = {}
    for d in graph.get("decisions") or []:
        by_part.setdefault(str(d.get("target_id")), []).append(d)

    print(f"\nbends on {len(tubes)} tube part(s):", flush=True)
    free_bends = []
    for p in tubes:
        pn = str(p.get("part_number"))
        decs = by_part.get(pn) or []
        bends = [d for d in decs if str(d.get("operation")).lower() in BEND_OPS]
        required = [d for d in bends if d.get("status") == "required"]
        print(f"\n  {pn}  ({p.get('description') or ''})")
        for d in bends:
            print(f"      {str(d.get('operation')):14s} {str(d.get('status')):16s} "
                  f"{str(d.get('reason') or '')[:64]}")
        if bends and not required:
            free_bends.append(pn)
            print("      ^^ RULED OUT WITH NOTHING IN ITS PLACE — this tube is bent for FREE")
        elif required:
            print(f"      -> charged as: {', '.join(str(d.get('operation')) for d in required)}")
        else:
            print("      (no bending claimed on this part — nothing to charge)")

    failed = False
    if free_bends:
        failed = True
        print(f"\nFAIL: {len(free_bends)} tube(s) would be bent for free: {', '.join(free_bends)}")
    if bad_lengths:
        failed = True
        print(f"\nFAIL: {len(bad_lengths)} tube(s) priced from a fallback figure that is not a "
              f"length: {', '.join(bad_lengths)}")
    if failed:
        return 1
    print("\nPASS: every tube that states a bend carries a required bending operation, and "
          "every priced tube length is a reading or a flagged INDICATIVE fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
