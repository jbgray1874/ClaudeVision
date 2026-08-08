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
    decisions = ((doc.get("canonical_route") or {}).get("decisions") or [])
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
    bad = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        code = str(p.get("part_number") or "")
        if not suffix(code):
            continue
        for key in ("materials", "material", "normalized_material", "raw_material"):
            v = p.get(key)
            for m in (v if isinstance(v, list) else [v]):
                if m and "CARD" in str(m).upper():
                    bad.append((code, key, m))
    if bad:
        print(f"   {len(bad)} reading(s) of CARD on a part whose code says we cut it:")
        for c, k, m in bad[:6]:
            print(f"      {c}: {k}={m!r}")
    else:
        print("   no CARD readings on suffixed parts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
