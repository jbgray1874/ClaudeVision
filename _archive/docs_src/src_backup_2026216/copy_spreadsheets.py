#!/usr/bin/env python3
"""
Copy all Excel spreadsheets from a source directory (and subfolders) 
to a target folder without moving the originals.

Usage Examples:
    python copy_spreadsheets.py --source "C:\Input\Spreadsheets" --target "C:\AI_Processing\Sheets"
    python copy_spreadsheets.py --source "C:\Input" --target "C:\AI_Processing" --flat
"""
import shutil
import argparse
from pathlib import Path

def is_excel_file(file_path: Path) -> bool:
    """Check if file is an Excel spreadsheet."""
    excel_extensions = {'.xls', '.xlsx', '.xlsm', '.xlsb'}
    if file_path.name.startswith('~'):      # Skip temporary Excel files
        return False
    return file_path.suffix.lower() in excel_extensions

def copy_spreadsheets(source_dir: str, target_dir: str, preserve_structure: bool = True):
    """Recursively copy all spreadsheets."""
    source_path = Path(source_dir).resolve()
    target_path = Path(target_dir).resolve()

    if not source_path.exists():
        print(f"❌ Error: Source directory not found: {source_path}")
        return

    target_path.mkdir(parents=True, exist_ok=True)
    print(f"🔍 Source : {source_path}")
    print(f"📁 Target : {target_path}")
    print(f"   Structure: {'Preserved' if preserve_structure else 'Flattened'}\n")

    copied_count = 0
    skipped_count = 0

    for file_path in source_path.rglob("*"):
        if file_path.is_file() and is_excel_file(file_path):
            try:
                if preserve_structure:
                    relative_path = file_path.relative_to(source_path)
                    dest_file = target_path / relative_path
                    log_name = str(relative_path)
                else:
                    dest_file = target_path / file_path.name
                    log_name = file_path.name

                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_file)
                print(f"✅ Copied: {log_name}")
                copied_count += 1
            except Exception as e:
                print(f"❌ Failed {file_path.name}: {e}")
                skipped_count += 1

    print("\n" + "="*70)
    print("✅ FINISHED!")
    print(f"   Copied  : {copied_count} spreadsheet(s)")
    print(f"   Skipped : {skipped_count} file(s)")
    print(f"   Target  : {target_path}")
    print("="*70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Copy all Excel spreadsheets from source to target (recursively)"
    )
    parser.add_argument(
        "--source", 
        required=True,
        help="Source directory to scan for spreadsheets"
    )
    parser.add_argument(
        "--target", 
        required=True,
        help="Destination directory to copy files to"
    )
    parser.add_argument(
        "--flat", 
        action="store_true",
        help="Flatten all files into one folder (no subfolders preserved)"
    )
    args = parser.parse_args()

    copy_spreadsheets(
        source_dir=args.source,
        target_dir=args.target,
        preserve_structure=not args.flat
    )