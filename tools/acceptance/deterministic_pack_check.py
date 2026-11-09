#!/usr/bin/env python3
"""SCRUM-194 acceptance, requirement 1: the deterministic reader against the original drawing.

Runs the engine's own PDF scanner on a pack's ORIGINAL drawing with every language-model and
vision reader off, and compares what it extracted and linked with an expected-facts file that a
person drafted from the drawing and a reviewer checked. It never reads a previous estimate as
the answer, and it never says "charged": the scan stage can establish that a fact was
EXTRACTED AND LINKED to its part, nothing more. Whether it reached the costing input and the
workbook row is requirement 2, the retention trace, checked on the costed record.

    python tools/acceptance/deterministic_pack_check.py 0358141
    python tools/acceptance/deterministic_pack_check.py 0358141 --mode pdf-only
    python tools/acceptance/deterministic_pack_check.py --all

Two modes, named on every report (the reviewer, 9 Nov 2026: "LLM/vision disabled" must not
quietly disable the deterministic SolidWorks or DXF readers in packs that have them):

    deterministic   every model reader off; the deterministic BOM reader, DXF flat patterns and
                    the SolidWorks extract stay on.  The full deterministic pipeline.
    pdf-only        as above, with SolidWorks and DXF discovery off too.  The PDF's own text.

A pack is a folder under tests/acceptance/packs/<pack>/ holding expected_facts.json. Its
drawing is customer data and is never committed (.gitignore: *.pdf): the harness looks for it
beside the facts file, then under $SDI_ACCEPTANCE_PACKS/<pack>/. A pack whose drawing is not
there is reported NOT TESTED, exit code 2, never counted as a pass.

Exit codes: 0 every strict fact extracted and linked; 1 a strict fact missing or wrong;
2 nothing could be tested (drawing missing, scanner failed).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "tests" / "acceptance" / "packs"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

NOT_TESTED, PASS, FAIL = 2, 0, 1
TOL_MM = 1.0


# ── the drawing ─────────────────────────────────────────────────────────────────────────

def find_drawing(pack_dir: Path, facts: Dict[str, Any]) -> Optional[Path]:
    name = str(facts.get("source_pdf") or "")
    roots = [pack_dir]
    env = os.getenv("SDI_ACCEPTANCE_PACKS", "").strip()
    if env:
        roots.append(Path(env) / pack_dir.name)
    for root in roots:
        if name and (root / name).is_file():
            return root / name
        pdfs = sorted(root.glob("*.pdf")) if root.is_dir() else []
        if len(pdfs) == 1:
            return pdfs[0]
    return None


def reader_switches(mode: str) -> Dict[str, str]:
    env = {"SDI_DETERMINISTIC_ONLY": "1", "SDI_LLM_FULL_EXTRACT": "0",
           "SKIP_VISION_EXTRACTION": "1", "SDI_DXF_LLM_INTERPRET": "0"}
    if mode == "pdf-only":
        env["SDI_APPLY_SOLIDWORKS"] = "0"
    return env


def scan(pdf: Path, mode: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    """The engine's own scan, model readers off. Returns (summary, parts, readers line)."""
    os.environ.update(reader_switches(mode))
    import file_scan
    import run_readers
    with contextlib.redirect_stdout(io.StringIO()):
        summary, _paths = file_scan.scan_pdf_file(
            pdf, auto_discover_dxf=(mode != "pdf-only"))
    parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    ran = run_readers.readers_that_ran(llm_only=False, deterministic_only=True,
                                       dxf_enabled=(mode != "pdf-only"),
                                       solidworks_enabled=(mode != "pdf-only"))
    on = [r["key"] for r in ran if r.get("ran")]
    off = [r["key"] for r in ran if not r.get("ran")]
    return summary, parts, f"readers on: {', '.join(on) or 'none'}; off: {', '.join(off) or 'none'}"


# ── what the scan says about each part ──────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def observe(part: Dict[str, Any]) -> Dict[str, Any]:
    ss = part.get("section_stock") if isinstance(part.get("section_stock"), dict) else {}
    ops = {str(o).strip().lower() for k in ("textual_operations", "inferred_operations", "operations")
           for o in (part.get(k) or []) if str(o).strip()}
    thk = _f(part.get("normalized_thickness_mm"))
    if thk is None:
        vals = [_f(x) for x in (part.get("thicknesses_mm") or [])]
        vals = [v for v in vals if v]
        thk = vals[-1] if len(set(vals)) == 1 else None
    blank = [_f(part.get("blank_length_mm") or part.get("overall_length_mm")),
             _f(part.get("blank_width_mm") or part.get("overall_width_mm"))]
    return {
        "pages": sorted(int(p) for p in (part.get("pages") or []) if str(p).isdigit()),
        "material": (part.get("materials") or [None])[0],
        "thickness_mm": thk,
        "section": [ss.get("a"), ss.get("b"), ss.get("t")] if ss.get("a") else None,
        "length_mm": _f(ss.get("length_mm")) if ss else None,
        "cut_lengths_mm": sorted(_f(x) for x in (ss.get("cut_lengths_mm") or []) if _f(x)) or None,
        "quantity": _f(part.get("quantity")),
        "operations": sorted(ops - {"handling"}),
        "blank_mm": blank if any(blank) else None,
        "bound_to_list": part.get("bound_to_parts_list_page"),
        "flags": [str(f) for f in (part.get("review_flags") or [])],
    }


def _same(a: Any, b: Any) -> bool:
    fa, fb = _f(a), _f(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= TOL_MM
    return str(a or "").strip().upper() == str(b or "").strip().upper()


def _same_list(a: Any, b: Any) -> bool:
    a, b = list(a or []), list(b or [])
    return len(a) == len(b) and all(_same(x, y) for x, y in zip(sorted(a, key=_f), sorted(b, key=_f)))


# ── the comparison ──────────────────────────────────────────────────────────────────────

def compare(expected: Dict[str, Any], parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per expected fact: extracted_and_linked | mismatch | not_found."""
    by_pn: Dict[str, Dict[str, Any]] = {}
    for p in parts:
        pn = str(p.get("part_number") or "").strip()
        if pn:
            by_pn[pn.upper()] = p
            by_pn[re.sub(r"\s+", "", pn.upper())] = p
    rows: List[Dict[str, Any]] = []
    for pn, want in (expected.get("parts") or {}).items():
        key = pn.upper()
        rec = by_pn.get(key) or by_pn.get(re.sub(r"\s+", "", key))
        if rec is None and want.get("listed_as"):
            rec = by_pn.get(str(want["listed_as"]).upper())
        page_of = want.get("page_of") or {}

        def row(fact: str, exp: Any, got: Any, ok: Optional[bool]) -> None:
            rows.append({"part": pn, "fact": fact, "expected": exp, "observed": got,
                         "page": page_of.get(fact, want.get("pages")),
                         "strict": bool(want.get("strict", {}).get(fact, True)) if isinstance(
                             want.get("strict"), dict) else bool(want.get("strict", True)),
                         "status": ("not_found" if rec is None or ok is None else
                                    "extracted_and_linked" if ok else "mismatch")})

        if rec is None:
            for fact in [k for k in want if k not in ("page_of", "strict", "listed_as", "note")]:
                row(fact, want[fact], None, None)
            continue
        got = observe(rec)
        for fact, exp in want.items():
            if fact in ("page_of", "strict", "listed_as", "note"):
                continue
            if fact == "pages":
                row(fact, exp, got["pages"], set(exp) <= set(got["pages"]) and not got["bound_to_list"])
            elif fact in ("material",):
                row(fact, exp, got["material"], _same(exp, got["material"]))
            elif fact in ("thickness_mm", "length_mm", "quantity"):
                row(fact, exp, got[fact], _same(exp, got[fact]) if got[fact] is not None else None)
            elif fact in ("section", "cut_lengths_mm", "blank_mm"):
                row(fact, exp, got[fact], _same_list(exp, got[fact]) if got[fact] else None)
            elif fact == "operations_present":
                missing = [o for o in exp if o not in got["operations"]]
                row(fact, exp, got["operations"], not missing)
            elif fact == "operations_absent":
                present = [o for o in exp if o in got["operations"]]
                row(fact, exp, present, not present)
            elif fact == "no_section":
                row(fact, exp, got["section"], (got["section"] is None) == bool(exp))
            elif fact == "flag_contains":
                hit = [f for f in got["flags"] if str(exp).lower() in f.lower()]
                row(fact, exp, hit[:1], bool(hit))
            else:
                row(fact, exp, None, None)
    return rows


# ── the costed record, joined (requirement 2 on the same rows) ──────────────────────────

_LEDGER_SUFFIX = {"material": ".material", "thickness_mm": ".size", "blank_mm": ".size",
                  "section": ".section", "length_mm": ".section", "cut_lengths_mm": ".section",
                  "quantity": ".quantity"}


def costing_results(record_path: Optional[Path], xlsx: Optional[Path]) -> Dict[str, Any]:
    """The drawing ledger's dispositions on the costed record, by (part, ledger suffix), plus
    the record's provenance. {} when no record was given."""
    if record_path is None:
        return {}
    import drawing_read_ledger as drl
    import read_charge_contract as rcc
    rec = json.loads(Path(record_path).read_text(encoding="utf-8"))
    final = rec.get("final_estimate") if isinstance(rec.get("final_estimate"), dict) else {}
    out: Dict[str, Any] = {"record": str(record_path), "read_back": final.get("source") == "excel_calculated",
                           "engine": str((rec.get("run_provenance") or {}).get("engine_build") or "?"),
                           "deterministic_only": bool(rec.get("deterministic_only")), "items": {}}
    ledger = rec.get("drawing_ledger")
    if not isinstance(ledger, dict) or not ledger.get("items"):
        ledger = drl.capture(rec)
        out["ledger_provenance"] = "RECONSTRUCTED from the record's parts: cannot prove nothing was lost earlier"
    else:
        out["ledger_provenance"] = "captured by the run at scan"
    if not out["read_back"]:
        out["why"] = f"no calculated workbook read-back (final_estimate.source is {final.get('source')!r})"
        return out
    snapshot = None
    if xlsx:
        try:
            import final_charge_contract as fcc
            snapshot = fcc.snapshot_xlsx(xlsx)
        except Exception:                                            # noqa: BLE001
            snapshot = None
    res = rcc.audit(rec, snapshot, ledger=ledger)
    for it in res.get("items") or []:
        out["items"].setdefault(re.sub(r"\s+", " ", str(it.get("record") or "")).upper(), {})[str(it.get("id"))] = it
    # An engine allowance beside the facts (a saw on a stated section) and a purchase of the
    # parts list are not drawing-ledger items; they are priced and listed, and the row says so.
    out["allowances"] = {}
    for a in res.get("allowances") or []:
        out["allowances"].setdefault(re.sub(r"\s+", " ", str(a.get("part") or "")).upper(), {})[str(a.get("operation"))] = a
    out["lines"] = {re.sub(r"\s+", " ", str(l.get("record") or "")).upper(): l for l in res.get("lines_noted") or []}
    out["issues"] = res.get("issues") or []
    out["verified_against_file"] = bool(snapshot)
    return out


def _costing_cell(row: Dict[str, Any], costing: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    """(text for the costing/workbook column, ok) — ok None where this fact has no charge."""
    if not costing:
        return "not evaluated (scan stage; give --record for the costed run)", None
    if not costing.get("read_back"):
        return f"NOT TESTED: {costing.get('why')}", None
    fact = row["fact"]
    items = costing["items"].get(re.sub(r"\s+", " ", row["part"]).upper()) or {}
    if fact in ("pages", "listed_as", "flag_contains", "no_section"):
        return "n/a (a reading, not a charge)", None
    pn_key = re.sub(r"\s+", " ", row["part"]).upper()
    line = (costing.get("lines") or {}).get(pn_key)
    if line and not items:
        return f"{line.get('class')}: {line.get('basis')} {', '.join(str(c) for c in line.get('cells') or [] if c)}".strip(), True
    if fact == "operations_present":
        allow = (costing.get("allowances") or {}).get(pn_key) or {}
        parts, oks = [], []
        for o in row["expected"]:
            i = next((i for k, i in items.items() if k.endswith(f".op.{o}")), None)
            if i:
                parts.append(f"{o}: {i['state']} {', '.join(i.get('cells') or [])}".strip())
                oks.append(i["state"] in ("charged", "covered", "excluded"))
            elif o in allow:
                a = allow[o]
                parts.append(f"{o}: engine allowance priced {a.get('cell') or ''} ({a.get('basis') or ''})".strip())
                oks.append(bool(a.get("cell")) and not a.get("holds"))
            else:
                parts.append(f"{o}: no ledger item and no allowance")
                oks.append(False)
        return "; ".join(parts), all(oks)
    if fact == "operations_absent":
        charged = [o for o in row["expected"] if any(k.endswith(f".op.{o}") and i.get("state") == "charged"
                                                       for k, i in items.items())]
        return ("none charged" if not charged else f"charged although absent: {charged}"), not charged
    suf = _LEDGER_SUFFIX.get(fact)
    it = next((i for k, i in items.items() if suf and k.endswith(suf)), None)
    if not items:
        return "no ledger item for this part on the costed record", False
    if it is None:
        return f"no {suf} item on the ledger", False
    good = it["state"] in ("charged", "covered", "carried", "corrected", "excluded")
    return f"{it['state']}: {it.get('how') or ''} {', '.join(it.get('cells') or [])}".strip(), good


def verdict(row: Dict[str, Any], costing_ok: Optional[bool], costing: Dict[str, Any]) -> str:
    read_ok = row["status"] == "extracted_and_linked"
    if costing and not costing.get("read_back"):
        return "NOT TESTED"
    if not read_ok:
        return "FAIL" if row["strict"] else "ADVISORY"
    if costing_ok is False:
        return "FAIL"
    return "PASS" if costing else "PASS (reading)"


# ── the report ──────────────────────────────────────────────────────────────────────────

def render(pack: str, mode: str, pdf: Optional[Path], sha: str, readers: str, rows: List[Dict[str, Any]],
           build: str, status: str, costing: Dict[str, Any]) -> str:
    out = [f"# Acceptance: {pack}", "",
           f"- drawing: {pdf.name if pdf else 'NOT FOUND'}  sha256 {sha[:16]}…" if sha else f"- drawing: {pdf.name if pdf else 'NOT FOUND'}",
           f"- test mode: **{mode}**  ({readers})",
           f"- engine build (scan): {build}",
           (f"- costed record: {Path(costing['record']).name}  engine {costing.get('engine')}  "
            f"deterministic-only {costing.get('deterministic_only')}  ledger {costing.get('ledger_provenance')}  "
            f"workbook file read: {'yes' if costing.get('verified_against_file') else 'no'}") if costing
           else "- costed record: none given (scan stage only; requirement 2 needs --record)",
           f"- result: **{status}**", "",
           "| Finding | Page | Expected | Reader result | Costing / workbook result | Verdict |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        mark = {"extracted_and_linked": "extracted and linked", "mismatch": "MISMATCH",
                "not_found": "NOT FOUND"}[r["status"]]
        out.append(f"| {r['part']} {r['fact']} | {r['page']} | {json.dumps(r['expected'])} | "
                   f"{json.dumps(r['observed'])} ({mark}) | {r.get('costing_text') or ''} | **{r['verdict']}** |")
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    out += ["", f"verdicts: {json.dumps(counts)}"]
    if costing.get("issues"):
        out += ["", "costed record issues:"] + [f"- {i.get('code')}: {i.get('item') or ''} {i.get('why') or i.get('text') or ''}"
                                               for i in costing["issues"][:20]]
    out += ["", "A fact extracted and linked at the scan stage is the first check only. With a costed record it "
                "must reach the correct charge or carry an explicit disposition; without one the verdict says "
                "(reading)."]
    return "\n".join(out) + "\n"


def check_pack(pack: str, mode: str, out_dir: Optional[Path] = None, record: Optional[Path] = None,
               xlsx: Optional[Path] = None) -> Tuple[int, str]:
    pack_dir = PACKS / pack
    facts_path = pack_dir / "expected_facts.json"
    if not facts_path.is_file():
        return NOT_TESTED, f"NOT TESTED: {pack}: no expected_facts.json under {pack_dir}"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    pdf = find_drawing(pack_dir, facts)
    if pdf is None:
        return NOT_TESTED, (f"NOT TESTED: {pack}: drawing '{facts.get('source_pdf')}' not beside "
                            f"{facts_path.name} and not under $SDI_ACCEPTANCE_PACKS/{pack}/")
    import hashlib
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    try:
        summary, parts, readers = scan(pdf, mode)
    except Exception as exc:                                         # noqa: BLE001
        return NOT_TESTED, f"NOT TESTED: {pack}: the scanner failed: {exc!r}"
    rows = compare(facts, parts)
    try:
        costing = costing_results(record, xlsx)
    except Exception as exc:                                         # noqa: BLE001
        costing = {"record": str(record), "read_back": False, "why": f"the record could not be read: {exc!r}"}
    for r in rows:
        text, ok = _costing_cell(r, costing)
        r["costing_text"], r["costing_ok"] = text, ok
        r["verdict"] = verdict(r, ok, costing)
    fails = [r for r in rows if r["verdict"] == "FAIL"]
    if costing and not costing.get("read_back"):
        code, status = NOT_TESTED, f"NOT TESTED on the costed record ({costing.get('why')}); reading: " + (
            "all strict facts extracted and linked" if not any(
                r["status"] != "extracted_and_linked" and r["strict"] for r in rows) else "strict facts open")
    else:
        code = PASS if not fails else FAIL
        status = "PASS" if code == PASS else f"FAIL ({len(fails)} fact(s))"
    build = str((summary.get("run_provenance") or {}).get("engine_build")
                or (summary.get("estimate_summary") or {}).get("engine_build") or "?")
    text = render(pack, mode, pdf, sha, readers, rows, build, status, costing)
    out_dir = out_dir or Path(os.getenv("SDI_ACCEPTANCE_OUT") or (ROOT / "output" / "acceptance"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (out_dir / f"{pack}_{mode}_{stamp}.md").write_text(text, encoding="utf-8")
    (out_dir / f"{pack}_{mode}_{stamp}.json").write_text(json.dumps(
        {"pack": pack, "mode": mode, "drawing": str(pdf), "drawing_sha256": sha, "readers": readers,
         "engine": build, "status": status, "rows": rows,
         "costed_record": {k: v for k, v in costing.items() if k != "items"},
         "reader_findings": (summary.get("reader_findings") or {})},
        indent=1, default=str), encoding="utf-8")
    return code, text


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packs", nargs="*", help="pack folder names under tests/acceptance/packs/")
    ap.add_argument("--all", action="store_true", help="every pack that has an expected_facts.json")
    ap.add_argument("--mode", choices=("deterministic", "pdf-only"), default="deterministic")
    ap.add_argument("--record", type=Path, default=None,
                    help="the costed run's _record.json: each fact is then also held to its charge")
    ap.add_argument("--xlsx", type=Path, default=None, help="the run's workbook, read for its own cells")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    packs = args.packs or ([p.name for p in sorted(PACKS.iterdir())
                            if (p / "expected_facts.json").is_file()] if args.all else [])
    if not packs:
        ap.error("name a pack, or --all")
    if args.record and len(packs) != 1:
        ap.error("--record goes with one pack")
    worst = PASS
    summary_lines = []
    for pack in packs:
        code, text = check_pack(pack, args.mode, args.out, args.record, args.xlsx)
        print(text)
        summary_lines.append(f"- {pack}: {'PASS' if code == PASS else 'FAIL' if code == FAIL else 'NOT TESTED'}")
        worst = max(worst, code) if code != NOT_TESTED else (worst if worst == FAIL else NOT_TESTED)
    if len(packs) > 1:
        print("# Packs\n" + "\n".join(summary_lines))
    return worst


if __name__ == "__main__":
    sys.exit(main())
