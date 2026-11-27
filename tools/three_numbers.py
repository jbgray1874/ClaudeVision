r"""The three signals that say whether a run is clean, and nothing else.

Not a report. A measurement, printed the same way every time so two runs can be compared
by reading rather than by remembering:

  1. OWNERSHIP     a purchase recognised in prose can name its sheet, and has a parent
  2. CORROBORATION how much charged labour nothing read off the drawing
  3. MATERIAL      a part whose code says we cut it, whose material says otherwise

Takes the latest scan JSON for a job, or a path.

    C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\tools\three_numbers.py
    C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\tools\three_numbers.py <job-or-path>
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _latest(pattern: str):
    hits = glob.glob(pattern)
    return max(hits, key=os.path.getmtime) if hits else None


def _findings(doc):
    """Invariant findings, wherever this run wrote them."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("code") and ("severity" in node or "message" in node):
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return out


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg and os.path.isfile(arg):
        path = arg
    else:
        root = Path(__file__).resolve().parents[1] / "output" / "json"
        path = _latest(str(root / f"*{arg}*.json")) if arg else _latest(str(root / "*.json"))
    if not path:
        print("no scan JSON found"); return 2
    doc = json.load(open(path, encoding="utf-8"))
    print(f"reading {os.path.basename(path)}\n")

    parts = doc.get("parts") or []
    findings = _findings(doc)

    # ── 1. OWNERSHIP ────────────────────────────────────────────────────────────────
    print("1. OWNERSHIP")
    prose = [p for p in parts if isinstance(p, dict)
             and "prose" in str(p.get("source") or "").lower()]
    if not prose:
        print("   no prose-recognised purchases on this job")
    for p in prose:
        code = p.get("part_number")
        print(f"   {code}: source_page={p.get('source_page')!r} pages={p.get('pages')!r}")
    _disc = [f for f in findings if "disconnected" in str(f.get("code") or "")]
    print(f"   disconnected-node findings: {len(_disc)}")
    for f in _disc[:3]:
        print(f"      {str(f.get('message') or '')[:150]}")

    # WHY AN EDGE DID NOT FORM. A page on the part is necessary and not sufficient: the
    # page must be an ASSEMBLY page of a drawing the job already knows, and the record the
    # COMPILER sees must still carry the page — which is not always the record the reader
    # wrote. Printing all three turns "still disconnected" into one of three answers.
    print("   assembly pages that can own (page -> drawing):")
    _owners = {}
    for _pg in (doc.get("pages") or []):
        if not isinstance(_pg, dict):
            continue
        _role = ((_pg.get("page_role") or {}) if isinstance(_pg.get("page_role"), dict)
                 else {}).get("primary_role")
        _num = _pg.get("page_number")
        if str(_role or "").strip().lower() == "assembly" and _num is not None:
            _owners[_num] = "assembly"
        print(f"      page {_num}: role={str(_role or '?')!r}")
    if not _owners:
        print("      NONE — no page is classified as an assembly page, so no page can own")

    _unowned = set()
    for f in _disc:
        _m = str(f.get("message") or "")
        for _p in parts:
            _c = str((_p or {}).get("part_number") or "")
            if _c and _c in _m:
                _unowned.add(_c)
    _mw = ((doc.get("manufacturing_writeup") or {}).get("parts") or [])
    _pe = ((doc.get("estimate_summary") or {}).get("part_estimates") or [])
    print("   does the record the COMPILER sees still carry the page?")
    for _code in sorted(_unowned):
        for _label, _pool in (("manufacturing_writeup", _mw), ("part_estimates", _pe)):
            _hit = next((r for r in _pool if isinstance(r, dict)
                         and str(r.get("part_number") or "") == _code), None)
            if _hit is None:
                print(f"      {_code} in {_label}: ABSENT")
            else:
                print(f"      {_code} in {_label}: source_page={_hit.get('source_page')!r} "
                      f"pages={_hit.get('pages')!r}")

    # ── 2. CORROBORATION ────────────────────────────────────────────────────────────
    print("\n2. CORROBORATION")
    _unc = [f for f in findings if f.get("code") == "route_operation_not_corroborated"]
    if _unc:
        d = _unc[0].get("detail") or {}
        print(f"   uncorroborated labour: {d.get('share_pct')}% "
              f"(GBP {d.get('value_gbp')} across {d.get('count')} operation(s)) "
              f"[{_unc[0].get('severity')}]")
    else:
        print("   no uncorroborated-route finding (either all corroborated, or the check "
              "found no canonical route decisions)")
    # The key the compiler writes. Reading doc["canonical_route"] reported "required
    # operations: 0" on a job with twelve of them — the instrument lying in the same way
    # the check it was measuring did, and for the same reason.
    _shadow = ((doc.get("estimate_summary") or {}).get("canonical_route_shadow")
               or doc.get("canonical_route_shadow") or {})
    decisions = (_shadow.get("decisions") or [])
    req = [d for d in decisions if isinstance(d, dict) and d.get("status") == "required"]
    quoted = [d for d in req if str(d.get("evidence") or "").strip()]
    print(f"   required operations: {len(req)}   carrying an evidence quote: {len(quoted)}")
    for d in quoted[:4]:
        print(f"      {d.get('operation')} on {d.get('target_id')}: "
              f"{str(d.get('evidence'))[:60]!r} ({d.get('evidence_where')})")

    # ── 3. MATERIAL ─────────────────────────────────────────────────────────────────
    print("\n3. MATERIAL")
    try:
        import part_code_conventions as pcc
        suffix = pcc.material_suffix
    except Exception:
        suffix = lambda s: (str(s or "").strip().upper()[-1:]
                            if str(s or "").strip().upper()[-1:] in "MAT" else "")
    # RAW READING vs CONCLUSION, side by side. Reporting only that "Card" appears somewhere
    # on a part cannot tell a broken arbitration from a working one whose loser is still
    # being displayed — and those need opposite fixes. The workbook costs these parts as
    # MILD STEEL, so the question is which field the estimator is being shown.
    rows = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        code = str(p.get("part_number") or "")
        if not suffix(code):
            continue
        raw = p.get("materials") or p.get("material") or p.get("raw_material")
        if isinstance(raw, list):
            raw = ", ".join(str(v) for v in raw if v)
        rows.append((code, raw, p.get("normalized_material"),
                     p.get("material_source") or p.get("normalized_material_source")))
    if not rows:
        print("   no material-suffixed parts on this job")
    _wrong = [r for r in rows if r[2] and "CARD" in str(r[2]).upper()]
    _stale = [r for r in rows if "CARD" in str(r[1] or "").upper()
              and r[2] and "CARD" not in str(r[2]).upper()]
    for code, raw, norm, src in rows[:8]:
        print(f"      {code:16} raw={str(raw)!r:24} costed={str(norm)!r:14} source={src!r}")
    print(f"   costed as CARD (arbitration failing): {len(_wrong)}")
    print(f"   raw says CARD, costed otherwise (display only): {len(_stale)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
