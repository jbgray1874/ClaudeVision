"""Read-only probe of a saved job record's sheet blanks, bought items and quantities (D-582):

    python tools/diagnose/check_material_quantity_coverage.py output/json/<stem>.json [--workbook output/estimates/<book>.xlsx] [--out proof.json]

Prints the material contract's audit — mismatches and unverified evidence apart, with a trace
row per part and the quantity roll-up trace — and exits 2 where it does not pass. Without a
workbook the saved cells are unverified, which is reported, not assumed. Nothing is written
unless --out names a file; the record and the workbook are never modified. Do not pair an
overwritten record with a different run's workbook. Probe as proposed in the Codex review
package of 22 Oct 2026.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from material_charge_contract import audit  # noqa: E402
from final_charge_contract import snapshot_xlsx  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("record")
    p.add_argument("--workbook")
    p.add_argument("--out")
    a = p.parse_args()
    doc = json.loads(Path(a.record).read_text(encoding="utf-8-sig"))
    result = audit(doc, snapshot_xlsx(a.workbook) if a.workbook else None)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(f"\n{len(result['issues'])} mismatch(es), {len(result['unverified'])} unverified "
          f"evidence item(s), {len(result['trace'])} part(s) traced", file=sys.stderr)
    sys.exit(0 if result["passed"] else 2)
