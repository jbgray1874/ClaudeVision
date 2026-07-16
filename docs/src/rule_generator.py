"""
SDIAIVision — Rule Generator
================================
Automatically generates new normalisation rules when patterns
are confirmed by estimators 3+ times.

These rules are written directly into json_normaliser.py so
they become part of the core scan pipeline — not just database
overrides but permanent code fixes.

Run nightly, or trigger manually after a correction batch.

Usage:
    python rule_generator.py             # generate + preview
    python rule_generator.py --apply     # generate + write to json_normaliser.py
"""

import re
import sys
import ast
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

try:
    import corrections_db as db
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    print("[rule_generator] WARNING: corrections_db not available")


# ── Paths ──────────────────────────────────────────────────────────────────────
_SRC_DIR    = Path(__file__).parent
_NORMALISER = _SRC_DIR / "json_normaliser.py"
_BACKUP_DIR = _SRC_DIR.parent / "data" / "rule_backups"


# ══════════════════════════════════════════════════════════════════════════════
# PATTERN EXTRACTORS
# Analyse the corrections database for learnable patterns
# ══════════════════════════════════════════════════════════════════════════════

def find_material_correction_patterns(min_count: int = 3) -> List[Dict]:
    """
    Find material corrections seen >= min_count times.
    These are strong candidates for auto-rules.
    """
    if not _DB_AVAILABLE:
        return []
    with db._connect() as conn:
        rows = conn.execute("""
            SELECT
                field_name,
                ai_value,
                correct_value,
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT part_number) as parts,
                GROUP_CONCAT(DISTINCT job_number) as jobs
            FROM corrections
            WHERE field_name = 'normalized_material'
              AND ai_value IS NOT NULL
              AND correct_value IS NOT NULL
            GROUP BY field_name, ai_value, correct_value
            HAVING count >= ?
            ORDER BY count DESC
        """, (min_count,)).fetchall()
        return [dict(r) for r in rows]


def find_part_number_patterns(min_count: int = 3) -> List[Dict]:
    """
    Find part number suffix patterns where the same material
    correction has been made consistently.
    e.g. "-xxM" parts always corrected to MILD_STEEL
    """
    if not _DB_AVAILABLE:
        return []
    with db._connect() as conn:
        rows = conn.execute("""
            SELECT part_number, correct_value, COUNT(*) as count
            FROM corrections
            WHERE field_name = 'normalized_material'
            GROUP BY part_number, correct_value
            HAVING count >= 1
        """).fetchall()

    # Analyse suffix patterns
    suffix_map: Dict[str, Dict[str, int]] = {}
    for row in rows:
        pn = str(row["part_number"] or "")
        mat = str(row["correct_value"] or "")
        m = re.search(r'-(\d+)([TMAatma])$', pn)
        if m:
            sfx = m.group(2).upper()
            key = f"{sfx}→{mat}"
            suffix_map[key] = suffix_map.get(key, {"count": 0, "parts": []})
            suffix_map[key]["count"] += 1
            suffix_map[key]["parts"].append(pn)

    patterns = []
    for key, data in suffix_map.items():
        if data["count"] >= min_count:
            sfx, mat = key.split("→")
            patterns.append({
                "suffix": sfx,
                "material": mat,
                "count": data["count"],
                "parts": data["parts"],
            })
    return patterns


def find_description_patterns(min_count: int = 3) -> List[Dict]:
    """
    Find description keywords that consistently map to a material.
    e.g. "CORNER PROTECTOR" always MILD_STEEL
    """
    if not _DB_AVAILABLE:
        return []
    # Would need description stored in corrections — future enhancement
    return []


# ══════════════════════════════════════════════════════════════════════════════
# RULE WRITERS
# Generate Python code snippets for json_normaliser.py
# ══════════════════════════════════════════════════════════════════════════════

def generate_material_override_code(patterns: List[Dict]) -> str:
    """Generate Python code for material value overrides."""
    if not patterns:
        return ""
    lines = [
        "    # ── Auto-generated material overrides (from estimator corrections) ──────",
        f"    # Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    for p in patterns:
        ai_val   = str(p["ai_value"]).upper()
        corr_val = str(p["correct_value"])
        count    = p["count"]
        lines.append(
            f"    if str(raw or '').strip().upper() == {ai_val!r}:"
            f"  # auto-rule: seen {count}x"
        )
        lines.append(f"        return {corr_val!r}")
    return "\n".join(lines)


def generate_suffix_rule_code(patterns: List[Dict]) -> str:
    """Generate Python code for part number suffix rules."""
    if not patterns:
        return ""
    lines = [
        "    # ── Auto-generated suffix rules (from estimator corrections) ────────────",
        f"    # Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    for p in patterns:
        sfx  = p["suffix"].upper()
        mat  = p["material"]
        count = p["count"]
        lines.append(
            f"    # suffix -{sfx}: {mat} (confirmed {count} times)"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISER PATCHER
# Safely insert generated rules into json_normaliser.py
# ══════════════════════════════════════════════════════════════════════════════

_AUTO_RULE_START = "    # ── AUTO-GENERATED RULES START ────────────────────────────────────────\n"
_AUTO_RULE_END   = "    # ── AUTO-GENERATED RULES END ──────────────────────────────────────────\n"


def patch_normaliser(new_rules_code: str, dry_run: bool = True) -> bool:
    """
    Insert auto-generated rules into json_normaliser.py.
    Replaces any existing auto-generated block.
    Validates syntax before writing.
    """
    if not _NORMALISER.exists():
        print(f"[rule_generator] Cannot find {_NORMALISER}")
        return False

    source = _NORMALISER.read_text(encoding="utf-8")

    # Build new auto-rules block
    new_block = (
        _AUTO_RULE_START
        + new_rules_code
        + "\n"
        + _AUTO_RULE_END
    )

    # Replace existing block if present
    if _AUTO_RULE_START in source:
        start_idx = source.index(_AUTO_RULE_START)
        end_idx   = source.index(_AUTO_RULE_END) + len(_AUTO_RULE_END)
        patched   = source[:start_idx] + new_block + source[end_idx:]
    else:
        # Insert before "return normalise_material(raw)"
        anchor = "    return normalise_material(raw)\r\n"
        if anchor not in source:
            anchor = "    return normalise_material(raw)\n"
        if anchor not in source:
            print("[rule_generator] Cannot find insertion anchor in normaliser")
            return False
        patched = source.replace(anchor, new_block + anchor, 1)

    # Validate syntax
    try:
        ast.parse(patched)
    except SyntaxError as e:
        print(f"[rule_generator] Syntax error in generated code: {e}")
        return False

    if dry_run:
        print("[rule_generator] DRY RUN — rules not written. Pass --apply to commit.")
        print("Generated rules:")
        print(new_rules_code)
        return True

    # Backup original
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"json_normaliser_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
    _NORMALISER.with_suffix(".py").write_text(source, encoding="utf-8")
    backup.write_text(source, encoding="utf-8")
    print(f"[rule_generator] Backup: {backup}")

    # Write patched file
    _NORMALISER.write_text(patched, encoding="utf-8")
    print(f"[rule_generator] Patched: {_NORMALISER}")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# REPORT
# Summary of what patterns have been found
# ══════════════════════════════════════════════════════════════════════════════

def print_report() -> None:
    """Print a human-readable report of learnable patterns."""
    print("\nSDIAIVision — Rule Generator Report")
    print("=" * 55)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    mat_patterns = find_material_correction_patterns(min_count=2)
    sfx_patterns = find_part_number_patterns(min_count=2)

    print(f"Material correction patterns (≥2 corrections same direction):")
    if mat_patterns:
        for p in mat_patterns:
            ready = "✅ RULE READY" if p["count"] >= 3 else "⏳ needs 1 more"
            print(f"  {ready} | {p['ai_value']!r} → {p['correct_value']!r} "
                  f"({p['count']}x) | jobs: {p.get('jobs','?')}")
    else:
        print("  None yet — corrections will appear here after estimators submit feedback")

    print()
    print(f"Part number suffix patterns (≥2 same suffix→material):")
    if sfx_patterns:
        for p in sfx_patterns:
            ready = "✅ RULE READY" if p["count"] >= 3 else "⏳ needs more data"
            print(f"  {ready} | suffix -{p['suffix']} → {p['material']} ({p['count']}x)")
    else:
        print("  None yet")

    if _DB_AVAILABLE:
        stats = db.get_learning_stats()
        print()
        print("Database state:")
        for k, v in stats.items():
            print(f"  {k:<35} {v}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# NIGHTLY JOB
# Run this on a schedule to keep the normaliser up to date
# ══════════════════════════════════════════════════════════════════════════════

def run_nightly(apply: bool = False) -> None:
    """
    Nightly learning job:
    1. Find patterns ready for rule generation
    2. Generate code
    3. Patch normaliser (if --apply)
    4. Print report
    """
    print_report()

    mat_patterns = find_material_correction_patterns(min_count=3)
    code_parts = []

    if mat_patterns:
        code_parts.append(generate_material_override_code(mat_patterns))

    if code_parts:
        all_code = "\n\n".join(code_parts)
        patch_normaliser(all_code, dry_run=not apply)
    else:
        print("[rule_generator] No patterns ready for rule generation yet.")
        print("  Keep scanning and submitting corrections — rules auto-generate at 3+ confirmations.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SDIAIVision Rule Generator")
    parser.add_argument("--apply",  action="store_true",
                        help="Write generated rules to json_normaliser.py")
    parser.add_argument("--report", action="store_true",
                        help="Print pattern report only")
    args = parser.parse_args()

    if args.report:
        print_report()
    else:
        run_nightly(apply=args.apply)
