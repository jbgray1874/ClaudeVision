"""
migrate_bought_in_catalogue.py
==============================
Migrates dbo.bought_in_parts into AIEstimating.BoughtInCatalogue:
  1. De-duplicates by canonical SKU (picks best description/price per group)
  2. Resolves / creates Supplier records
  3. Inserts into BoughtInCatalogue with source='migrated:dbo.bought_in_parts'
  4. Marks migrated rows is_active=0 in dbo.bought_in_parts

Also inserts the Trestle job's specific items from AIEstimating.vCurrentBoughtIn
that are not already present in BoughtInCatalogue (26 Trestle rows, seeded from
workbook:11087-17-GA).

Run with --dry-run first to preview. No DB changes until you confirm.

Usage:
    python migrate_bought_in_catalogue.py --dry-run
    python migrate_bought_in_catalogue.py --write
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed")
    sys.exit(1)

# ── Connection ─────────────────────────────────────────────────────────────────
CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.200;"
    "DATABASE=SDILive;"
    "UID=AIBot;"
    "PWD=AIAgentPW2026;"
    "Encrypt=yes;TrustServerCertificate=yes;"
)

# ── Canonical SKU map ──────────────────────────────────────────────────────────
# Maps all known aliases → one canonical SKU.
# Keeps the most meaningful/stable code, drops duplicates.
SKU_ALIASES: Dict[str, str] = {
    # Pallets — various codes all mean the same SDI pallet
    "PALLET1":          "PALLET-STD",
    # Powder coats
    "POWDER24":         "POWDER-RAL7016-SG",
    "POWDER184":        "POWDER-RAL9005-GL",
    # Boxes
    "BOX-296x404x40":   "BOX-296x404x40",   # keep
    "BOX2038":          "H349206",           # alias → H349206
    # VKF scanner profiles — multiple code formats for same item
    "VKF DBR18":        "VKF-DBR18",
    "DBR18":            "VKF-DBR18",
    "VKF:DBR18":        "VKF-DBR18",
    "VKF DBR39":        "VKF-DBR39",
    "DBR39":            "VKF-DBR39",
    "VKF:DBR39":        "VKF-DBR39",
    # UKPOS pusher rail — 4 codes, one item
    "FIXING22081":      "UKPOS-SHFP28",
    "SHFP28":           "UKPOS-SHFP28",
    "UKPOS:SHFP28":     "UKPOS-SHFP28",
    "FIXING2081":       "UKPOS-SHFP28",
    # LED panel — job-specific, keep but flag
    "10919-LED":        "10919-LED",
    # Standard parts
    "4x12mm WOOD SCREW":"SCREW-4x12-WOOD",
    "No8x12mm WOOD SCREW BLACK": "SCREW-8x12-BLK",
    "PACKAGING":        "PACKAGING-STD",
    "SUNDRIES-STD":     "SUNDRIES-STD",
}

# Items that are job-specific / not generic SDI standards — flagged in source_note
JOB_SPECIFIC = {"10919-LED", "7350845", "429009000002"}

# ── Category inference ─────────────────────────────────────────────────────────
def infer_category(desc: str, sku: str) -> str:
    d = (desc or "").upper()
    s = (sku or "").upper()
    if any(x in d for x in ["PALLET", "EURO PALLET"]):           return "pallet"
    if any(x in d for x in ["BOX", "CARTON", "PACKAGING"]):      return "box"
    if "POWDER" in d or ("RAL" in d and "SCREW" not in d):       return "powder"
    if "LED" in d or "LIGHT" in d or "LENS" in d or "CNC CLEAR" in d: return "bought_in"
    if any(x in d for x in ["SCREW", "BOLT", "RIVET", "INSERT",
                              "MAGNET", "CASTOR", "PUSHER",
                              "KNURLED", "NUTSERT"]):             return "fixing"
    if "FIXING" in s and "EDGING" not in d:                      return "fixing"
    if any(x in d for x in ["MDF", "PLYWOOD"]):                  return "board"
    if any(x in d for x in ["ACRYLIC", "PERSPEX", "GREENCAST"]): return "board"
    if "EDGING" in d or "RUBUSEC" in d:                          return "edging"
    if any(x in d for x in ["STICKER", "LABEL", "UPC"]):         return "label"
    if any(x in d for x in ["PROFILE", "SCANNER"]):              return "profile"
    if "KEY STEEL" in d or ("BAR" in d and "KEY" in d):          return "material"
    if any(x in d for x in ["DELIVERY", "CARRIAGE"]):            return "delivery"
    if "SUNDRIES" in d:                                           return "sundries"
    return "fixing"


def infer_uom(desc: str, category: str) -> str:
    d = (desc or "").upper()
    if category in ("pallet", "box", "label"):  return "each"
    if "ROLL" in d or "/MTR" in d or "MTR" in d: return "metre"
    if "PER M" in d:                             return "metre"
    if category == "powder":                     return "each"
    return "each"


# ── De-duplication logic ───────────────────────────────────────────────────────
def canonical_sku(raw_sku: Optional[str]) -> str:
    if not raw_sku:
        return ""
    return SKU_ALIASES.get(raw_sku.strip(), raw_sku.strip())


def dedup_rows(rows: List[Tuple]) -> List[Dict[str, Any]]:
    """
    rows: (part_code, description, unit_price_gbp, supplier_name, source_note)
    Returns one record per canonical SKU, picking the most informative description
    and most recent price.
    """
    groups: Dict[str, List[Dict]] = {}
    for part_code, desc, price, supplier, source in rows:
        sku = canonical_sku(part_code)
        key = sku or re.sub(r"\s+", " ", (desc or "").strip().upper())[:60]
        record = {
            "raw_sku": part_code,
            "canonical_sku": sku,
            "description": (desc or "").strip(),
            "unit_price_gbp": float(price or 0),
            "supplier_name": (supplier or "").strip(),
            "source_note": (source or "").strip(),
        }
        groups.setdefault(key, []).append(record)

    deduped = []
    for key, group in groups.items():
        # Pick longest description (most informative)
        best = max(group, key=lambda r: len(r["description"]))
        # Clean doubled words in description (e.g. "Pusher Pusher")
        import re as _re
        best["description"] = _re.sub(r'\b(\w+) \1\b', r'\1', best["description"])
        # Use highest price if there's variance (conservative)
        best["unit_price_gbp"] = max(r["unit_price_gbp"] for r in group)
        # Collect all source notes
        sources = list(dict.fromkeys(r["source_note"] for r in group if r["source_note"]))
        best["source_note"] = " | ".join(sources[:3])
        deduped.append(best)

    return sorted(deduped, key=lambda r: r["canonical_sku"] or r["description"])


# ── Supplier resolution ────────────────────────────────────────────────────────
def get_or_create_supplier(cur, name: str, category: str, write: bool) -> Optional[int]:
    if not name:
        return None
    cur.execute(
        "SELECT supplier_id FROM AIEstimating.Supplier WHERE UPPER(name) = UPPER(?)",
        [name]
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    if write:
        cur.execute(
            """INSERT INTO AIEstimating.Supplier (name, category, active, created_utc)
               VALUES (?, ?, 1, GETUTCDATE())""",
            [name, category]
        )
        cur.execute("SELECT @@IDENTITY")
        return int(cur.fetchone()[0])
    return None  # dry run — return None


# ── Already in catalogue? ──────────────────────────────────────────────────────
def already_in_catalogue(cur, sku: str, desc: str) -> bool:
    if sku:
        cur.execute(
            "SELECT 1 FROM AIEstimating.BoughtInCatalogue WHERE UPPER(supplier_sku) = UPPER(?)",
            [sku]
        )
        if cur.fetchone():
            return True
    cur.execute(
        """SELECT 1 FROM AIEstimating.BoughtInCatalogue
           WHERE UPPER(LTRIM(RTRIM(description))) = UPPER(LTRIM(RTRIM(?)))""",
        [desc]
    )
    return bool(cur.fetchone())


# ── Main ───────────────────────────────────────────────────────────────────────
def run(write: bool) -> None:
    mode = "WRITE" if write else "DRY RUN"
    print(f"\n{'='*60}")
    print(f"  migrate_bought_in_catalogue.py  [{mode}]")
    print(f"{'='*60}\n")

    conn = pyodbc.connect(CONN_STR, timeout=15)
    cur = conn.cursor()

    # ── 1. Fetch dbo.bought_in_parts ──────────────────────────────────────────
    cur.execute("""
        SELECT part_code, description, unit_price_gbp, supplier_name, source_note
        FROM dbo.bought_in_parts
        WHERE is_active = 1
        ORDER BY supplier_name, part_code
    """)
    raw_rows = cur.fetchall()
    print(f"dbo.bought_in_parts active rows: {len(raw_rows)}")

    deduped = dedup_rows(raw_rows)
    print(f"After de-duplication: {len(deduped)} unique items\n")

    # ── 2. Preview / insert each item ────────────────────────────────────────
    inserted = 0
    skipped = 0
    suppliers_created = 0

    for item in deduped:
        sku  = item["canonical_sku"]
        desc = item["description"]
        cat  = infer_category(desc, sku)
        uom  = infer_uom(desc, cat)
        flag = " [JOB-SPECIFIC]" if sku in JOB_SPECIFIC else ""

        if already_in_catalogue(cur, sku, desc):
            print(f"  SKIP (exists): {sku or '—':30s} {desc[:45]}")
            skipped += 1
            continue

        sup_id = get_or_create_supplier(cur, item["supplier_name"], cat, write)
        if item["supplier_name"] and sup_id is None and write:
            suppliers_created += 1

        source = "migrated:dbo.bip"  # fits nvarchar(40)

        # Truncate all strings to safe column lengths
        sku_safe  = (sku or "")[:80]   or None  # nvarchar(80)
        desc_safe = desc[:300]  # nvarchar(300)
        cat_safe  = cat[:40]   # nvarchar(40)
        uom_safe  = uom[:20]
        src_safe  = source[:40]   # source col is nvarchar(40)

        print(f"  {'INSERT' if write else 'WOULD INSERT'}: "
              f"{sku or '—':30s} £{item['unit_price_gbp']:7.4f}  "
              f"{cat:10s} {desc[:40]}{flag}")

        if write:
            cur.execute(
                """INSERT INTO AIEstimating.BoughtInCatalogue
                   (supplier_id, supplier_sku, description, category, uom,
                    unit_price_gbp, currency, effective_from, source, version, created_utc)
                   VALUES (?, ?, ?, ?, ?, ?, 'GBP', ?, ?, 1, GETUTCDATE())""",
                [sup_id, sku_safe, desc_safe, cat_safe, uom_safe,
                 item["unit_price_gbp"], date.today().isoformat(), src_safe]
            )
        inserted += 1

    # ── 3. Mark dbo.bought_in_parts as migrated ───────────────────────────────
    if write:
        cur.execute("""
            UPDATE dbo.bought_in_parts
            SET is_active = 0,
                source_note = ISNULL(source_note,'') + ' [migrated to AIEstimating.BoughtInCatalogue]'
            WHERE is_active = 1
        """)
        print(f"\n  Marked {len(raw_rows)} dbo.bought_in_parts rows as inactive.")

    # ── 4. Summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  {'Inserted' if write else 'Would insert'}: {inserted}")
    print(f"  Skipped (already exists):  {skipped}")
    if write:
        cur.execute("SELECT COUNT(*) FROM AIEstimating.BoughtInCatalogue")
        total = cur.fetchone()[0]
        print(f"  BoughtInCatalogue total rows now: {total}")
    print(f"{'='*60}\n")

    if write:
        conn.commit()
        print("Committed. Run dry-run again to verify.\n")
    else:
        print("Dry run complete — no changes made.")
        print("Re-run with --write to apply.\n")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="Actually write to DB (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only (default)")
    args = parser.parse_args()
    run(write=args.write)
