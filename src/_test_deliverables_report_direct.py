r"""READ-ONLY of code, but WRITES a test report. FAST (no populate). Reproduce the deployed
--deliverables report-logic against the EXISTING 1282 JSON on disk: find the manual, build the
bundle, generate the PARITY-VARIANT rich report — in seconds. Confirms the wiring works end-to-end
without a full run. Uses the deployed _find_manual_workbook + job_report_html + estimate_full_parity.
"""
import sys, os
from pathlib import Path
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

canon = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
out_dir = r"C:\ClaudeVision\output\estimates"
scan_label = "1282 - Milwaukee Wall Bay"

import json
summary = json.loads(Path(canon).read_text(encoding="utf-8"))

# 1) deployed manual-lookup
import main as M
manual = M._find_manual_workbook(scan_label, summary)
print(f"manual found: {manual}")

bundle_path = None
if manual:
    from estimate_full_parity_report import generate_and_write as gen_bundle
    import re
    bj = Path(out_dir) / (re.sub(r"[^\w\- ]","",scan_label).strip() + "_parity_bundle.json")
    bc = bj.with_suffix(".csv")
    print("building parity bundle (reads the manual .xls + JSON)...")
    gen_bundle(Path(canon), Path(manual), bj, bc, read_via_excel=False)
    bundle_path = str(bj)
    print(f"bundle -> {bj}")

# 2) generate the rich report (parity variant if bundle, else new-job)
from job_report_html import generate_report
rpath = generate_report(canon, out_path=None, bundle_path=bundle_path, job_stem=scan_label)
print(f"\nRICH REPORT -> {rpath}")
print(f"variant: {'PARITY (with comparison)' if bundle_path else 'NEW-JOB (analysis only)'}")
# quick sanity: does it contain the parity section + real numbers?
h = Path(rpath).read_text(encoding="utf-8")
print(f"  has §1a parity section: {'Parity vs manual estimate' in h}")
print(f"  size: {len(h)} bytes")
print("\n-> open the HTML to eyeball the parity-variant report against real 1282 + manual.")
