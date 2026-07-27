r"""
Reconcile a job's deliverables against each other: the estimate JSON, the populated
workbook (.xlsx), the client quote HTML, and the job report HTML.

Purpose: prove the four artifacts agree on the headline figures before anything is sent
externally. The HTML is generated from the JSON, and the JSON is stamped from the
workbook by the wep-readback step, so they SHOULD line up — this checks that they DO,
and reads the .xlsx independently (not via the JSON) so a stale stamp or a silently
failed readback is caught rather than trusted.

    C:\ClaudeVision\.venv\Scripts\python.exe scripts\reconcile_deliverables.py
    C:\ClaudeVision\.venv\Scripts\python.exe scripts\reconcile_deliverables.py 0359131

Tolerance is 1p. Any row that does not agree is marked FAIL with the differing values.

Note on the .xlsx read: wb_populate writes Excel FORMULAS that compute on load. openpyxl
reads only cached values. If the file has not been opened/saved by Excel since it was
generated, the totals may read as blank here — the script says so rather than guessing.
The wep-readback step (which uses Excel itself) is the authoritative sheet read; the JSON
column below is that value.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

OUTPUT_ROOT = os.environ.get("SDI_OUTPUT_ROOT", r"C:\ClaudeVision\output")
TOL = 0.01
_SKIP = ("llm_extract", "audit", "writeback", "overflow", "parity")

try:
    import openpyxl  # noqa
except Exception:
    openpyxl = None


def _newest(pattern: str, must_skip=True):
    hits = glob.glob(os.path.join(OUTPUT_ROOT, "**", pattern), recursive=True)
    if must_skip:
        hits = [h for h in hits if not any(s in os.path.basename(h).lower() for s in _SKIP)]
    return max(hits, key=os.path.getmtime) if hits else None


def _money_from_text(text: str):
    """First £-amount in a string -> float, or None."""
    m = re.search(r"£\s*([-\d][\d,]*\.?\d*)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# ── source readers ────────────────────────────────────────────────────────────

def read_json(job: str):
    p = _newest(f"*{job}*.json")
    if not p:
        return None, {}
    doc = json.load(open(p, encoding="utf-8"))
    wep = ((doc.get("estimate_summary") or {}).get("workbook_equivalent_pricing")) or {}
    return p, {
        "unit": wep.get("m105_total_unit_cost_gbp") or wep.get("l105_total_unit_cost_gbp"),
        "material": wep.get("m59_material_subtotal_gbp"),
        "labour": wep.get("m103_labour_subtotal_gbp"),
    }


def read_xlsx(job: str):
    p = _newest(f"*{job}*.xlsx")
    if not p or openpyxl is None:
        return p, {}
    wb = openpyxl.load_workbook(p, data_only=True)
    ws = wb.active
    labels = {
        "unit": ("total unit cost",),
        "material": ("total material cost",),
        "labour": ("total labour cost",),
    }
    found = {"unit": None, "material": None, "labour": None}
    for row in ws.iter_rows():
        for cell in row:
            if not isinstance(cell.value, str):
                continue
            low = cell.value.strip().lower()
            for key, keys in labels.items():
                if found[key] is None and any(k in low for k in keys):
                    # take the right-most numeric value in this row
                    nums = [c.value for c in row if isinstance(c.value, (int, float))]
                    if nums:
                        found[key] = float(nums[-1])
    return p, found


def read_html(job: str, kind: str, field_regexes):
    """kind: 'quote' or 'report'. field_regexes: {field: compiled regex over the html}."""
    p = _newest(f"*{job}*_{kind}.html", must_skip=False)
    if not p:
        return None, {}
    html = open(p, encoding="utf-8", errors="replace").read()
    out = {}
    for field, rx in field_regexes.items():
        m = rx.search(html)
        out[field] = _money_from_text(m.group(0)) if m else None
    return p, out


QUOTE_RX = {
    "unit": re.compile(r'class="unit"[^>]*>\s*£[^<]+', re.I),
}
REPORT_RX = {
    "unit": re.compile(r'Unit Cost \(workbook\).*?class="val"[^>]*>\s*£[^<]+', re.I | re.S),
    "material": re.compile(r'>Material<.*?class="val"[^>]*>\s*£[^<]+', re.I | re.S),
    "labour": re.compile(r'>Labour<.*?class="val"[^>]*>\s*£[^<]+', re.I | re.S),
}


def _agree(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None  # not enough to compare
    return (max(nums) - min(nums)) <= TOL


def reconcile(job: str) -> bool:
    jp, j = read_json(job)
    xp, x = read_xlsx(job)
    qp, q = read_html(job, "quote", QUOTE_RX)
    rp, r = read_html(job, "report", REPORT_RX)

    print(f"\n=== {job} ===")
    for label, path in (("json  ", jp), ("xlsx  ", xp), ("quote ", qp), ("report", rp)):
        print(f"  {label}: {os.path.basename(path) if path else 'NOT FOUND'}")

    ok = True
    print(f"\n  {'FIELD':9} {'JSON(sheet)':>12} {'XLSX':>12} {'QUOTE':>12} {'REPORT':>12}   VERDICT")
    for field in ("unit", "material", "labour"):
        vals = [j.get(field), x.get(field), q.get(field), r.get(field)]
        agree = _agree(vals)
        verdict = "—" if agree is None else ("PASS" if agree else "*** FAIL ***")
        if agree is False:
            ok = False

        def fmt(v):
            return f"£{v:,.2f}" if isinstance(v, (int, float)) else "—"
        print(f"  {field:9} {fmt(vals[0]):>12} {fmt(vals[1]):>12} {fmt(vals[2]):>12} {fmt(vals[3]):>12}   {verdict}")

    if x.get("unit") is None and openpyxl is not None:
        print("  note: xlsx totals not cached — open the workbook in Excel once so it computes,")
        print("        then re-run; JSON(sheet) already reflects the Excel-computed value.")
    return ok


def main() -> None:
    jobs = sys.argv[1:] or ["0348837", "0357299", "0357831", "0359131"]
    results = {job: reconcile(job) for job in jobs}
    print("\n================ RECONCILIATION SUMMARY ================")
    for job, ok in results.items():
        print(f"  {job}: {'ALL FIELDS AGREE' if ok else 'MISMATCH — see above'}")
    print()
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
