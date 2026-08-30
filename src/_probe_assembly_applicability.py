#!/usr/bin/env python3
"""
_probe_assembly_applicability.py  —  READ-ONLY diagnostic. Writes nothing.

Purpose: work out a PRECISE, SAFE guard for when per-bay assembly/pack labour
(the E2 historical median) should apply, so a single flat fabricated part
(e.g. 1300-01 Flat Shelf) gets ZERO assembly labour while a genuine multi-part
bay (e.g. 1282 Milwaukee Wall Bay — the regression anchor) is left UNTOUCHED.

Run against the engine summary JSON for each job and eyeball the two side by side:

    C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_assembly_applicability.py ^
        "C:\\ClaudeVision\\output\\json\\1300-01FlatShelf.json"

    C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_assembly_applicability.py ^
        "C:\\ClaudeVision\\output\\json\\1282....json"

It reports, per job:
  - every part with its role, material, and unit estimate
  - the count of GENUINELY FABRICATED parts (excludes bought-in + PACKAGING/DELIVERY placeholders)
  - whether a bay / sub-assembly structure is present
  - what assembly_pack_labour the engine attached (basis + cost)
  - a proposed guard verdict for THIS job

Nothing here writes to disk or the DB. It only reads the summary JSON.
"""
import sys, json

PLACEHOLDER_NAMES = {"PACKAGING", "DELIVERY", "CARRIAGE", "HAULAGE"}
FABRICATED_MATERIALS = {
    "MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
    "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN", "GALVANISED", "ACRYLIC",
}


def _norm(s):
    return str(s or "").strip().upper()


def _is_placeholder(pe):
    pn = _norm(pe.get("part_number") or pe.get("name"))
    return any(pn == p or pn.startswith(p) for p in PLACEHOLDER_NAMES)


def _role(pe):
    roles = pe.get("page_roles") or pe.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return ",".join(roles) or (pe.get("page_role", {}) or {}).get("primary_role", "") or "?"


def _is_bought_in(pe):
    r = _norm(_role(pe))
    mat = _norm(pe.get("material") or pe.get("normalized_material"))
    basis = _norm(pe.get("pricing_basis") or "")
    return ("BOUGHT_IN" in r) or (mat == "BOUGHT_IN") or ("CUSTOMER_SUPPLIED" in basis)


def _is_fabricated(pe):
    if _is_placeholder(pe) or _is_bought_in(pe):
        return False
    mat = _norm(pe.get("material") or pe.get("normalized_material"))
    # a fabricated part is a steel/ali/acrylic sheet part with real geometry
    geom_ok = bool((pe.get("geometry") or {}).get("estimated_cut_length_mm")) \
        or (pe.get("geometry_source") in ("dxf_flat_pattern", "pdf")) and mat in FABRICATED_MATERIALS
    return mat in FABRICATED_MATERIALS and not _is_placeholder(pe)


def main(path):
    with open(path, "r", encoding="utf-8") as fh:
        s = json.load(fh)

    label = s.get("source_file") or path
    es = s.get("estimate_summary") or {}
    parts = es.get("part_estimates") or s.get("part_estimates") or []
    bay = s.get("bay_estimate") or {}
    asm = (bay.get("assembly_pack_labour") or {}) if isinstance(bay, dict) else {}

    print("=" * 78)
    print(f"JOB: {label}")
    print("=" * 78)
    print(f"{'part_number':<22}{'role':<14}{'material':<16}{'unit_gbp':>9}  fabricated?")
    print("-" * 78)
    fab = 0
    for pe in parts:
        pn = (pe.get("part_number") or pe.get("name") or "?")[:20]
        role = _role(pe)[:12]
        mat = (pe.get("material") or pe.get("normalized_material") or "?")[:14]
        unit = pe.get("unit_estimate_gbp")
        if unit is None:
            unit = pe.get("unit_estimate") or pe.get("extended_estimate") or 0
        f = _is_fabricated(pe)
        if f:
            fab += 1
        print(f"{pn:<22}{role:<14}{mat:<16}{float(unit or 0):>9.2f}  {'YES' if f else '-'}")

    print("-" * 78)
    print(f"TOTAL parts listed          : {len(parts)}")
    print(f"GENUINELY FABRICATED parts  : {fab}")

    # bay / sub-assembly structure signals
    bay_parts = bay.get("parts") or bay.get("bay_parts") or []
    subassemblies = bay.get("sub_assemblies") or bay.get("subassemblies") or []
    n_bays = bay.get("bay_count") or bay.get("bays") or s.get("bay_count")
    print(f"bay_estimate present        : {bool(bay)}")
    print(f"  bay_count                 : {n_bays}")
    print(f"  bay parts listed          : {len(bay_parts)}")
    print(f"  sub-assemblies listed     : {len(subassemblies)}")

    print(f"\nassembly_pack_labour attached:")
    print(f"  basis        : {asm.get('basis')}")
    print(f"  minutes/bay  : {asm.get('assembly_minutes_per_bay')}")
    print(f"  cost/bay £   : {asm.get('cost_per_bay_gbp')}")
    print(f"  flag         : {asm.get('flag')}")

    # proposed guard verdict
    print("\n" + "-" * 78)
    should_apply = fab > 1 or len(subassemblies) > 0 or (isinstance(n_bays, int) and n_bays > 1)
    verdict = "APPLY assembly labour (genuine multi-part / bay job)" if should_apply \
        else "SUPPRESS assembly labour -> £0 (single fabricated part, no assembly content)"
    print(f"PROPOSED GUARD VERDICT: {verdict}")
    print(f"  rule tested: apply IF (fabricated_parts>1) OR (sub_assemblies>0) OR (bay_count>1)")
    print("=" * 78)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_assembly_applicability.py <summary.json>")
        sys.exit(1)
    main(sys.argv[1])
