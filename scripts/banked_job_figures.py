r"""
Print the authoritative workbook figures for the banked jobs, straight from the saved
estimate JSON — no re-run required.

The numbers reported here are the ones Excel itself computed and the wep-readback step
stamped back into the JSON (material / labour / unit), plus the credibility-gate values.
Use this to fill or verify any figure quoted in a briefing, rather than reading a total
off a quote HTML (which shows unit price only and not the material/labour split).

    C:\ClaudeVision\.venv\Scripts\python.exe scripts\banked_job_figures.py
    C:\ClaudeVision\.venv\Scripts\python.exe scripts\banked_job_figures.py 0357831
"""
from __future__ import annotations

import glob
import json
import os
import sys

DEFAULT_JOBS = ["0348837", "0357299", "0357831", "0359131"]
OUTPUT_ROOT = os.environ.get("SDI_OUTPUT_ROOT", r"C:\ClaudeVision\output")

# Files that are not the canonical estimate JSON for a job
_SKIP = ("llm_extract", "audit", "writeback", "overflow", "parity")


def _newest_json(job: str) -> str | None:
    hits = [
        f for f in glob.glob(os.path.join(OUTPUT_ROOT, "**", f"*{job}*.json"), recursive=True)
        if not any(s in os.path.basename(f).lower() for s in _SKIP)
    ]
    return max(hits, key=os.path.getmtime) if hits else None


def _money(v) -> str:
    return f"£{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _pct(v) -> str:
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


def main() -> None:
    jobs = sys.argv[1:] or DEFAULT_JOBS
    rows = []

    for job in jobs:
        path = _newest_json(job)
        if not path:
            rows.append((job, "NO JSON FOUND", "—", "—", "—", "—", "—", ""))
            continue

        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)

        es = doc.get("estimate_summary") or {}
        wep = es.get("workbook_equivalent_pricing") or {}
        ds = es.get("data_sufficiency") or {}
        parts = es.get("part_estimates") or []

        rows.append((
            job,
            os.path.basename(path)[:46],
            _money(wep.get("m59_material_subtotal_gbp")),
            _money(wep.get("m103_labour_subtotal_gbp")),
            _money(wep.get("m105_total_unit_cost_gbp")),
            _pct(ds.get("dxf_part_ratio")),
            _pct(ds.get("credible_cost_ratio")),
            f"{len(parts)} parts · {ds.get('status') or 'ok'}",
        ))

    hdr = ("JOB", "SOURCE JSON", "MATERIAL", "LABOUR", "UNIT", "DXF", "CREDIBLE", "NOTE")
    widths = [max(len(str(r[i])) for r in (rows + [hdr])) for i in range(len(hdr))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(hdr))
    print()
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    print()
    print("Figures are Excel-computed totals stamped back into the JSON (wep-readback).")
    print("DXF = share of fabricated parts with a matched flat pattern; drives the")
    print("credibility gate. 0% means the unit cost is provisional, not reportable.")
    print()


if __name__ == "__main__":
    main()
