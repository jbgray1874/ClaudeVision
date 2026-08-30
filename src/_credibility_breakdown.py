"""
Read-only probe. Reads the 1282 run JSON and prints, per part:
  - part_number, page_roles (bought_in vs fabricated)
  - extended cost
  - price source / cost_method (where the price came from)
  - price_verified flag if present
  - whether it landed in data_sufficiency.unreliable_parts, and why

No DB, no writes. Just shows what the engine already produced.
Run: C:\\ClaudeVision\\.venv\\Scripts\\python.exe _credibility_breakdown.py
"""
import json
import sys
from pathlib import Path

DEFAULT = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"

def _g(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur

def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    # locate part estimates + data_sufficiency wherever they live in the doc
    part_estimates = (
        data.get("part_estimates")
        or _g(data, "estimate", "part_estimates")
        or _g(data, "document_estimate", "part_estimates")
        or []
    )
    ds = (
        data.get("data_sufficiency")
        or _g(data, "estimate", "data_sufficiency")
        or _g(data, "document_estimate", "data_sufficiency")
        or {}
    )
    unreliable = {str(u.get("part_number")): u for u in (ds.get("unreliable_parts") or [])}

    # source parts (for page_roles / material), keyed by part number
    source_parts = (
        data.get("parts")
        or data.get("source_parts")
        or _g(data, "document", "parts")
        or []
    )
    role_by_pn = {}
    mat_by_pn = {}
    for p in source_parts:
        pn = str(p.get("part_number") or "").strip()
        if pn:
            role_by_pn[pn] = p.get("page_roles") or []
            mat_by_pn[pn] = p.get("normalized_material")

    print(f"\nFILE: {path}")
    print(f"data_sufficiency.status        = {ds.get('status')}")
    print(f"credible_cost_gbp              = {ds.get('credible_cost_gbp')}")
    print(f"unreliable_cost_gbp            = {ds.get('unreliable_cost_gbp')}")
    print(f"credible_cost_ratio            = {ds.get('credible_cost_ratio')}")
    print(f"document_total_provisional_gbp = {ds.get('document_total_provisional_gbp')}")
    print(f"suppress_headline_total        = {ds.get('suppress_headline_total')}")
    print("=" * 110)
    hdr = f"{'PART':<26}{'ROLE':<14}{'EXT £':>8}  {'PRICE SOURCE / cost_method':<42}{'VERIF':<7}{'GATE'}"
    print(hdr)
    print("-" * 110)

    cred_boughtin = 0.0
    uncred_boughtin = 0.0
    cred_fab = 0.0
    uncred_fab = 0.0

    for est in part_estimates:
        pn = str(est.get("part_number") or "")
        roles = role_by_pn.get(pn) or est.get("page_roles") or []
        is_bi = "bought_in" in [str(r).lower() for r in roles]
        ext = float(est.get("extended_total_cost_gbp") or 0.0)

        # price source: try a few likely fields
        src = (
            est.get("cost_method")
            or est.get("costing_basis")
            or _g(est, "pricing", "source")
            or _g(est, "price", "source")
            or est.get("price_source")
            or "?"
        )
        verified = (
            est.get("price_verified")
            if est.get("price_verified") is not None
            else _g(est, "pricing", "price_verified")
        )
        vstr = "yes" if verified is True else ("no" if verified is False else "-")

        u = unreliable.get(pn)
        gate = ("UNCRED: " + ",".join(u.get("reasons", []))) if u else "credible"

        role_lbl = "bought_in" if is_bi else (str(mat_by_pn.get(pn) or "fab")[:12])

        if ext > 0:
            if is_bi:
                if u: uncred_boughtin += ext
                else: cred_boughtin += ext
            else:
                if u: uncred_fab += ext
                else: cred_fab += ext

        print(f"{pn:<26}{role_lbl:<14}{ext:>8.2f}  {str(src)[:42]:<42}{vstr:<7}{gate}")

    print("-" * 110)
    print(f"BOUGHT-IN  credible £{cred_boughtin:7.2f}   uncredible £{uncred_boughtin:7.2f}")
    print(f"FABRICATED credible £{cred_fab:7.2f}   uncredible £{uncred_fab:7.2f}")
    print(f"\n=> Of the uncredible bucket, bought-in accounts for £{uncred_boughtin:.2f} "
          f"and fabricated for £{uncred_fab:.2f}.")
    print("   If bought-in dominates, the gate is failing purchased parts on the wrong axis (no_part_dxf).")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
