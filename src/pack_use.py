#!/usr/bin/env python3
"""Found, read, linked, costed: what became of each drawing in a pack (reviewer, 12 Nov 2026).

"Report separately what was found, successfully read, linked and used in costing. Retain every
unresolved reference or specification visibly." "Finding a model file is not proof that it was
successfully read or supplied the required specification."

One line per pack member, from the run's own record and, where given, the pack's manifest:

  found    the member's files in the pack (formats)
  read     its model was read by SolidWorks or Document Manager, or a detail sheet was bound to it;
           a model that FAILED to open is named with the reader's own reason
  linked   a part record in the estimate carries its number
  costed   material and labour pounds charged against it, and the source of the material price

and after them: referenced drawings with no file, parts in the estimate that are in no pack, and
charges that rest on a weak source (a historical match, an allowance, a market figure).

    python src/pack_use.py --record <run>_record.json [--manifest pack_manifest.json] [--json out.json]

Reads only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

WEAK_SOURCES = ("historical", "allowance", "market", "llm", "ai_", "inferred", "default", "estimate")
_MODEL_TAIL = re.compile(r"\.(?:SLDPRT|SLDASM|SLDDRW)\d*$", re.I)


def key(text: Any) -> str:
    """Two spellings of one number compare equal: case, spaces, a model file's extension."""
    return re.sub(r"[\s_]", "", _MODEL_TAIL.sub("", str(text or "").strip())).upper()


def _pounds(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def model_failures(record: Dict[str, Any]) -> Dict[str, str]:
    """drawing key -> the reader's reason, for every model the run could not open."""
    out: Dict[str, str] = {}
    sw = record.get("solidworks_native") or {}
    for e in sw.get("extract_errors") or []:
        if isinstance(e, dict):
            path, why = str(e.get("path") or e.get("file") or ""), "; ".join(map(str, e.get("errors") or [e.get("error") or ""]))
        else:
            m = re.search(r"([^\\/]+\.SLD(?:PRT|ASM|DRW))", str(e), re.I)
            path, why = (m.group(1) if m else ""), str(e)
        if path:
            out[key(Path(path.replace("\\", "/")).name.split("_")[0])] = why[:300]
    return out


def trace(record: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    parts = {key(p.get("part_number")): p for p in record.get("parts") or [] if isinstance(p, dict)}
    mat = {key(r.get("part_number")): r for r in ((record.get("cost_breakdown") or {}).get("material") or {})
           .get("per_part") or [] if isinstance(r, dict)}
    failed = model_failures(record)
    rows: List[Dict[str, Any]] = []
    members = (manifest or {}).get("members") or [
        {"drawing": p.get("part_number"), "files": []} for p in record.get("parts") or []]
    seen = set()
    for m in members:
        k = key(m.get("drawing"))
        seen.add(k)
        p = parts.get(k)
        formats = sorted({str(f.get("format") or "").lower() for f in m.get("files") or [] if f.get("format")})
        has_model = any(f in ("sldprt", "sldasm") for f in formats)
        if k in failed:
            read = "MODEL NOT READ: " + failed[k]
        elif p is None:
            read = "not known: no part record"
        elif p.get("solidworks_native") or "solidworks" in str(p.get("geometry_source") or "").lower() \
                or "docmgr" in str(p.get("geometry_source") or "").lower():
            read = "model read (" + str(p.get("bbox_mm_source") or p.get("material_source") or "solidworks") + ")"
        elif any(str(r).lower() not in ("parts_list", "bom", "") for r in (p.get("page_roles") or [])) and p.get("pages"):
            read = "detail sheet bound"
        elif has_model:
            read = "MODEL FOUND, NOTHING TAKEN FROM IT"
        else:
            read = "no drawing of its own was read"
        row_m = mat.get(k) or {}
        material = _pounds(row_m.get("extended_material_cost_gbp"))
        source = str(row_m.get("supplier_source") or (p or {}).get("material_source") or "")
        rows.append({
            "drawing": m.get("drawing"), "found": formats, "read": read, "linked": p is not None,
            "material": (p or {}).get("normalized_material"), "thickness_mm": (p or {}).get("normalized_thickness_mm"),
            "blank_mm": (p or {}).get("_costed_blank_mm"), "material_gbp": material, "price_source": source,
            "weak_price": bool(material) and any(w in source.lower() for w in WEAK_SOURCES),
            "open": [str(f)[:200] for f in ((p or {}).get("review_flags") or [])][:4]})
    pack_refs = manifest or {}
    return {
        "drawing": record.get("declared_product") or record.get("job_output_stem"),
        "members": rows,
        "referenced_no_file": list(pack_refs.get("missing") or []),
        "bought_in_unmatched": list(pack_refs.get("bought_in_unmatched") or []),
        "parts_list_read": pack_refs.get("references_read"),
        "in_estimate_not_in_pack": sorted(str(p.get("part_number")) for k, p in parts.items()
                                          if manifest and k not in seen),
        "models_failed": failed,
        "weak_prices": [{"drawing": r["drawing"], "gbp": r["material_gbp"], "source": r["price_source"]}
                        for r in rows if r["weak_price"]],
        "not_read": [r["drawing"] for r in rows if r["read"].isupper() or r["read"].startswith(("MODEL", "no drawing"))],
        "not_linked": [r["drawing"] for r in rows if not r["linked"]],
        "linked_uncosted": [r["drawing"] for r in rows if r["linked"] and not r["material_gbp"]],
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", required=True)
    ap.add_argument("--manifest", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)
    record = json.loads(Path(a.record).read_text(encoding="utf-8"))
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8")) if a.manifest else None
    t = trace(record, manifest)
    print(f"{t['drawing']}: {len(t['members'])} member(s)"
          + ("" if manifest else "  (no manifest given: members are the estimate's own parts)"))
    print(f"  {'drawing':<26}{'found':<24}{'linked':<8}{'material £':>11}  read / price source")
    for r in t["members"]:
        print(f"  {str(r['drawing']):<26}{','.join(r['found']) or '-':<24}{'yes' if r['linked'] else 'NO':<8}"
              f"{r['material_gbp']:>11.2f}  {r['read']}"
              + (f" | {r['price_source']}{'  WEAK' if r['weak_price'] else ''}" if r["price_source"] else ""))
    for label, k in (("referenced, no file", "referenced_no_file"), ("bought-in, not matched", "bought_in_unmatched"),
                     ("in the estimate, in no pack", "in_estimate_not_in_pack"), ("not read", "not_read"),
                     ("not linked to a part", "not_linked"), ("linked, no material charged", "linked_uncosted")):
        if t.get(k):
            print(f"  {label}: " + ", ".join(map(str, t[k])))
    for w in t["weak_prices"]:
        print(f"  weak price: {w['drawing']} £{w['gbp']:.2f} from {w['source']}")
    if manifest is not None and not t.get("parts_list_read"):
        print("  the GA's parts list was not read: the pack is not proved complete")
    if a.json:
        Path(a.json).write_text(json.dumps(t, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
