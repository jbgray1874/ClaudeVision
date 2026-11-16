import argparse
from pathlib import Path

from concept_brief_extractor import build_concept_brief, write_concept_brief_json
from config import ensure_directories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract concept/client-originated PPTX/PDF/image briefs into concept JSON.")
    parser.add_argument("--input", required=True, help="Path to the PPTX, PDF, or image source file.")
    parser.add_argument("--json-output", help="Optional output path for the concept JSON.")
    parser.add_argument("--print-summary", action="store_true", help="Print a short summary after writing the JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_directories()

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input file not found: {source}")

    written = write_concept_brief_json(source, args.json_output)
    print(f"Concept brief JSON written to: {written}")

    if args.print_summary:
        brief = build_concept_brief(source)
        dims = brief.get("assembly_summary", {}).get("overall_dimensions_mm", {})
        totals = brief.get("cost_breakdown", {}).get("totals", {})
        print(f"Client: {brief.get('client')}")
        print(f"Product: {brief.get('product_name')}")
        print(f"Dimensions: L={dims.get('length')} D={dims.get('depth')} H={dims.get('height_including_wheels')}")
        print(f"Budgetary total GBP: {totals.get('grand_total_gbp')}")


if __name__ == "__main__":
    main()
