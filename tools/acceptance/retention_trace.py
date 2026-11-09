#!/usr/bin/env python3
"""SCRUM-194 acceptance, requirement 2: every drawing fact's final disposition on a costed run.

    python tools/acceptance/retention_trace.py --record <job>_record.json [--xlsx <book.xlsx>]

Takes a saved run record (the timestamped `..._record.json` beside its workbook) and holds every
fact the drawing's own text gave a part to the calculated workbook the run wrote:

    charged     a calculated row on the part names it, with money on it
    covered     another calculated charge carries it, named
    excluded    a person ruled it out for this job, with the reason
    unresolved  none of these: the release is held
    carried / corrected   a fact (quantity, material, size, section) reached the costed record
                as read, or was changed by a named source

The ledger is the record's own `drawing_ledger` where the run captured one, else captured here
from the record's parts (drawing_read_ledger.capture), and the audit is read_charge_contract's,
the same one that holds an LLM read. Nothing is called, nothing is changed. A record with no
calculated workbook read-back (final_estimate.source != excel_calculated) is NOT TESTED: nothing
can be shown to have reached a charged cell. With --xlsx the saved file's own cells are read as
well; without it the read-back is taken on trust and the report says so.

Exit codes: 0 nothing unresolved; 1 something unresolved or an issue; 2 not tested.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

NOT_TESTED, PASS, FAIL = 2, 0, 1


def _load(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a run record")
    return data


def trace(record: Path, xlsx: Optional[Path]) -> Dict[str, Any]:
    import drawing_read_ledger as drl
    import read_charge_contract as rcc
    try:
        import final_charge_contract as fcc
    except Exception:                                                # noqa: BLE001
        fcc = None
    summary = _load(record)
    final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), dict) else {}
    out: Dict[str, Any] = {"record": str(record), "xlsx": str(xlsx) if xlsx else None,
                           "engine": str((summary.get("run_provenance") or {}).get("engine_build")
                                         or (summary.get("estimate_summary") or {}).get("engine_build") or "?"),
                           "deterministic_only": bool(summary.get("deterministic_only"))}
    if final.get("source") != "excel_calculated":
        out.update(status="NOT TESTED",
                   why="the record holds no calculated workbook read-back (final_estimate.source "
                       f"is {final.get('source')!r}); nothing can be shown to reach a charged cell")
        return out
    ledger = summary.get("drawing_ledger")
    if not isinstance(ledger, dict) or not ledger.get("items"):
        ledger = drl.capture(summary)
        out["ledger_captured_here"] = True
    # THE TWO ARE NOT THE SAME EVIDENCE (reviewer, 9 Nov 2026): a ledger the run captured at
    # scan holds what the drawing stated before anything could drop it; one reconstructed here
    # from the record's parts is a diagnosis of that record and cannot prove nothing was lost.
    out["ledger_provenance"] = ("RECONSTRUCTED from the record's built parts: diagnosis only, it cannot "
                                "prove nothing was lost before the build" if out.get("ledger_captured_here")
                                else "captured by the run at scan, before costing")
    try:
        import findings_trace as ftr
        out["findings"] = ftr.audit(summary, None)
    except Exception as exc:                                         # noqa: BLE001
        out["findings"] = {"applicable": False, "why": f"{type(exc).__name__}: {exc}"}
    snapshot = fcc.snapshot_xlsx(xlsx) if (xlsx and fcc is not None) else None
    result = rcc.audit(summary, snapshot, ledger=ledger)
    if out["findings"].get("applicable"):
        out["findings"] = ftr.audit(summary, result)
    out["ledger"] = {"items": len(ledger.get("items") or []), "parts_read": ledger.get("parts_read")}
    out["items"] = result.get("items") or []
    out["issues"] = result.get("issues") or []
    out["counts"] = result.get("counts") or {}
    out["allowances"] = result.get("allowances") or []
    out["allowances_noted"] = result.get("allowances_noted") or []
    out["lines_noted"] = result.get("lines_noted") or []
    unresolved = [i for i in out["items"] if i.get("state") == "unresolved"]
    lost = [r for r in (out["findings"].get("items") or []) if r.get("verdict") == "FAIL"]
    out["status"] = ("PASS" if not unresolved and not out["issues"] and not lost else
                     f"FAIL ({len(unresolved)} unresolved, {len(out['issues'])} issue(s), {len(lost)} finding(s) lost)")
    out["verified_against_file"] = bool(snapshot)
    return out


def render(t: Dict[str, Any]) -> str:
    lines = [f"# Retention trace: {Path(t['record']).name}", "",
             f"- engine: {t['engine']}  deterministic-only run: {t['deterministic_only']}",
             f"- workbook file read: {'yes' if t.get('verified_against_file') else 'no (read-back taken on trust)'}",
             f"- drawing ledger: {t.get('ledger_provenance') or ''}",
             f"- result: **{t['status']}**", ""]
    if t["status"] == "NOT TESTED":
        return "\n".join(lines + [t["why"], ""])
    fnd = t.get("findings") or {}
    lines += ["## What the reader found, through the build, the costing and the workbook", ""]
    if not fnd.get("applicable"):
        lines += [f"NOT APPLICABLE: {fnd.get('why')}", ""]
    else:
        lines += [f"findings captured at {fnd.get('captured')}; verdicts {json.dumps(fnd.get('counts'))}", "",
                  "| Finding | Page | Part | Reader result | Built record | Costing | Workbook | Verdict |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in fnd.get("items") or []:
            rs, cs, ws = r.get("record") or {}, r.get("costing") or {}, r.get("workbook") or {}
            lines.append(f"| {r.get('id')} {r.get('kind')} | {r.get('page')} | {r.get('part') or 'UNASSIGNED'} | "
                         f"{json.dumps(r.get('value'))[:50]} {('(' + str(r.get('words'))[:40] + ')') if r.get('words') else ''} | "
                         f"{rs.get('state')} {rs.get('note') or ''} | {cs.get('state')} | "
                         f"{ws.get('state')} {', '.join(ws.get('cells') or [])} | **{r.get('verdict')}** |")
        lines.append("")
    lines += ["## What the drawing stated, held to the charged cells", ""]
    lines += ["| Item | Part | Page | As read | State | How | Cells |", "|---|---|---|---|---|---|---|"]
    for i in t["items"]:
        lines.append(f"| {i.get('id')} {i.get('label') or ''} | {i.get('record') or ''} | {i.get('page') or ''} | "
                     f"{json.dumps(i.get('as_read'))[:60]} | **{i.get('state')}** | {i.get('how') or ''} | "
                     f"{', '.join(i.get('cells') or [])} |")
    c = t["counts"]
    lines += ["", f"counts: {json.dumps(c)}"]
    if t["issues"]:
        lines += ["", "issues:"] + [f"- {i.get('code')}: {i.get('item') or ''} {i.get('why') or i.get('text') or ''}" for i in t["issues"][:30]]
    held = [a for a in t["allowances"] if a.get("holds")]
    if held:
        lines += ["", f"engine allowances holding the release: {len(held)}"]
    if t.get("allowances_noted"):
        lines += ["", "engine allowances beside the drawing's facts (priced, named, not a hold):"]
        lines += [f"- {a.get('item')} on {a.get('part') or 'the unit'}: {a.get('basis') or ''}"
                  f"{' ' + str(a.get('cell')) if a.get('cell') else ''}" for a in t["allowances_noted"]]
    if t.get("lines_noted"):
        lines += ["", "costed lines the drawing's sheets do not state (the engine's own, listed):"]
        lines += [f"- {l.get('record')} [{l.get('class')}]: {l.get('basis') or ''}"
                  f"{' ' + ', '.join(str(c) for c in l.get('cells') or [] if c) if l.get('cells') else ''}"
                  for l in t["lines_noted"]]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", required=True, type=Path)
    ap.add_argument("--xlsx", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    if not args.record.is_file():
        print(f"NOT TESTED: {args.record} is not there"); return NOT_TESTED
    if args.xlsx and not args.xlsx.is_file():
        print(f"NOT TESTED: {args.xlsx} is not there"); return NOT_TESTED
    t = trace(args.record, args.xlsx)
    text = render(t)
    print(text)
    out_dir = args.out or Path(os.getenv("SDI_ACCEPTANCE_OUT") or (ROOT / "output" / "acceptance"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    stem = args.record.stem
    (out_dir / f"{stem}_trace_{stamp}.md").write_text(text, encoding="utf-8")
    (out_dir / f"{stem}_trace_{stamp}.json").write_text(json.dumps(t, indent=1, default=str), encoding="utf-8")
    return NOT_TESTED if t["status"] == "NOT TESTED" else (PASS if t["status"] == "PASS" else FAIL)


if __name__ == "__main__":
    sys.exit(main())
