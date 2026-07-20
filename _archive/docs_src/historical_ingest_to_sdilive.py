"""
SDIAIVision — Historical Estimates Loader
==========================================
Loads the output from batch_ingest_historical.py into
SDILive.AIEstimating.HistoricalEstimates.

Once loaded, these 30,634 real SDI estimates become the
pricing baseline for the learning system — every new
estimate is calibrated against a decade of real costs.

Usage:
    # After batch_ingest_historical.py has run:
    python src\\historical_ingest_to_sdilive.py `
        --input "output\\historical_estimates" `
        --batch-size 500

    # Check status without loading:
    python src\\historical_ingest_to_sdilive.py --status
"""

import os
import json
import argparse
import glob
from pathlib import Path
from datetime import datetime

try:
    import corrections_db as db
    _DB_OK = True
except ImportError:
    _DB_OK = False
    print("ERROR: corrections_db.py not found in src\\")
    exit(1)


def count_existing() -> int:
    """How many historical records already in SDILive."""
    try:
        conn = db._connect()
        count = conn.cursor().execute(
            "SELECT COUNT(*) FROM AIEstimating.HistoricalEstimates"
        ).fetchval()
        conn.close()
        return count or 0
    except Exception as e:
        print(f"Cannot connect to SDILive: {e}")
        return -1


def find_input_files(input_dir: str) -> list:
    """Find all JSON/CSV files from batch_ingest_historical output."""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Input directory not found: {input_path}")
        print("Run batch_ingest_historical.py first:")
        print('  python src\\batch_ingest_historical.py --root "K:\\Estimating" --out "output\\historical_estimates" --force')
        return []
    files = (
        list(input_path.glob("**/*.json")) +
        list(input_path.glob("**/*.csv"))
    )
    return sorted(files)


def parse_estimate_json(filepath: Path) -> list:
    """
    Parse one output JSON from batch_ingest_historical.
    Returns list of row dicts ready for SDILive insertion.
    """
    rows = []
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            data = json.load(f)
    except Exception:
        return rows

    # Handle different output formats from batch_ingest
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Could be a single estimate or wrapper
        records = data.get("parts", data.get("estimates", [data]))
    else:
        return rows

    source_file = str(filepath.name)

    for rec in records:
        if not isinstance(rec, dict):
            continue

        # Extract job/drawing number from filepath if not in record
        path_parts = filepath.parts
        job_num = rec.get("job_number") or rec.get("job") or _extract_job_from_path(filepath)
        drawing_num = (rec.get("drawing_number") or rec.get("drawing")
                       or rec.get("part_number", "")[:20] or "")

        unit_cost = _to_float(
            rec.get("unit_estimate") or rec.get("unit_cost") or
            rec.get("cost_per_unit") or rec.get("unit_price") or 0
        )
        total_cost = _to_float(
            rec.get("extended_estimate") or rec.get("total_cost") or
            rec.get("extended_cost") or
            (unit_cost * _to_int(rec.get("quantity", 1)))
        )

        if unit_cost <= 0 and total_cost <= 0:
            continue  # Skip £0 records — not useful for learning

        row = {
            "source_file":    source_file,
            "job_number":     str(job_num or "")[:50],
            "drawing_number": str(drawing_num or "")[:100],
            "part_number":    str(rec.get("part_number") or "")[:100],
            "description":    str(rec.get("description") or "")[:500],
            "material":       str(rec.get("normalized_material") or
                                  rec.get("material") or "")[:100],
            "thickness_mm":   _to_float(rec.get("thickness_mm") or
                                         rec.get("thicknesses") or 0),
            "quantity":       _to_int(rec.get("quantity", 1)),
            "unit_cost":      unit_cost,
            "total_cost":     total_cost,
            "estimator":      str(rec.get("estimator") or "")[:100],
            "customer":       str(rec.get("customer") or "")[:200],
            "estimate_date":  _parse_date(rec.get("date") or
                                           rec.get("estimate_date") or ""),
        }
        rows.append(row)

    return rows


def load_into_sdilive(input_dir: str, batch_size: int = 500,
                      dry_run: bool = False) -> None:
    """
    Main loader: reads all JSON files from input_dir,
    inserts records into SDILive.AIEstimating.HistoricalEstimates.
    """
    files = find_input_files(input_dir)
    if not files:
        return

    existing = count_existing()
    print(f"\nSDIAIVision — Historical Estimates Loader")
    print("=" * 55)
    print(f"  Input directory:  {input_dir}")
    print(f"  Files found:      {len(files):,}")
    print(f"  Already in DB:    {existing:,}")
    print(f"  Batch size:       {batch_size}")
    print(f"  Mode:             {'DRY RUN' if dry_run else 'LIVE — writing to SDILive'}")
    print()

    if dry_run:
        # Just show what would be loaded
        sample_rows = []
        for f in files[:5]:
            sample_rows.extend(parse_estimate_json(f))
        print(f"Sample of first {len(sample_rows)} records:")
        for r in sample_rows[:10]:
            print(f"  {r['job_number']:<12} {r['part_number']:<20} "
                  f"{r['material']:<15} £{r['unit_cost']:.2f}")
        print()
        print("Run without --dry-run to load into SDILive.")
        return

    # Load in batches
    total_inserted = 0
    total_skipped  = 0
    batch = []

    try:
        conn = db._connect()
        cursor = conn.cursor()
    except Exception as e:
        print(f"Cannot connect to SDILive: {e}")
        return

    for i, filepath in enumerate(files):
        rows = parse_estimate_json(filepath)
        batch.extend(rows)

        # Insert batch when full or on last file
        if len(batch) >= batch_size or i == len(files) - 1:
            if batch:
                inserted, skipped = _insert_batch(cursor, batch)
                total_inserted += inserted
                total_skipped  += skipped
                conn.commit()

                if (i + 1) % 50 == 0 or i == len(files) - 1:
                    pct = ((i + 1) / len(files)) * 100
                    print(f"  [{pct:5.1f}%] Files: {i+1:,}/{len(files):,} | "
                          f"Inserted: {total_inserted:,} | Skipped: {total_skipped:,}")
                batch = []

    conn.close()

    print()
    print("=" * 55)
    print(f"COMPLETE")
    print(f"  Records inserted: {total_inserted:,}")
    print(f"  Records skipped:  {total_skipped:,} (zero cost or duplicate)")
    print(f"  Total in SDILive: {count_existing():,}")
    print()
    print("SDILive.AIEstimating.HistoricalEstimates is ready.")
    print("The learning system will now use historical pricing as context.")


def _insert_batch(cursor, batch: list) -> tuple:
    """Insert a batch of rows. Returns (inserted, skipped)."""
    inserted = 0
    skipped  = 0
    for row in batch:
        try:
            cursor.execute("""
                INSERT INTO AIEstimating.HistoricalEstimates
                (SourceFile, JobNumber, DrawingNumber, PartNumber,
                 Description, Material, ThicknessMm, Quantity,
                 UnitCost, TotalCost, Estimator, Customer, EstimateDate)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                row["source_file"],   row["job_number"],
                row["drawing_number"],row["part_number"],
                row["description"],   row["material"],
                row["thickness_mm"],  row["quantity"],
                row["unit_cost"],     row["total_cost"],
                row["estimator"],     row["customer"],
                row["estimate_date"] or None,
            )
            inserted += 1
        except Exception:
            skipped += 1
    return inserted, skipped


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_float(val) -> float:
    try:
        if isinstance(val, list):
            val = val[0] if val else 0
        return float(str(val).replace("£", "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _to_int(val) -> int:
    try:
        return max(1, int(float(str(val or 1))))
    except (ValueError, TypeError):
        return 1


def _parse_date(val) -> str:
    if not val:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_job_from_path(filepath: Path) -> str:
    """Try to extract a job number from the file path."""
    import re
    for part in reversed(filepath.parts):
        m = re.search(r'\b(\d{4,6})\b', part)
        if m:
            return m.group(1)
    return ""


def print_status(input_dir: str) -> None:
    """Print current ingestion status."""
    files = find_input_files(input_dir)
    existing = count_existing()
    print(f"\nSDIAIVision — Historical Ingestion Status")
    print("=" * 50)
    print(f"  Output files in {input_dir}: {len(files):,}")
    print(f"  Records in SDILive:          {existing:,}")
    if existing == 0 and len(files) == 0:
        print()
        print("  → batch_ingest_historical.py has not run yet.")
        print("  → Run tonight with:")
        print('     python src\\batch_ingest_historical.py')
        print('       --root "K:\\Estimating"')
        print('       --out "output\\historical_estimates"')
        print('       --force')
    elif existing == 0 and len(files) > 0:
        print()
        print(f"  → {len(files):,} output files exist but not yet loaded.")
        print("  → Run: python src\\historical_ingest_to_sdilive.py")
        print("           --input output\\historical_estimates")
    else:
        print(f"  → System has {existing:,} historical pricing records.")
        print("  → Learning system is using these for cost calibration.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load historical estimates into SDILive"
    )
    parser.add_argument("--input",      default="output\\historical_estimates",
                        help="Folder containing batch_ingest output JSON files")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run",    action="store_true",
                        help="Preview without writing to SDILive")
    parser.add_argument("--status",     action="store_true",
                        help="Show ingestion status only")
    args = parser.parse_args()

    if args.status:
        print_status(args.input)
    else:
        load_into_sdilive(args.input, args.batch_size, args.dry_run)
