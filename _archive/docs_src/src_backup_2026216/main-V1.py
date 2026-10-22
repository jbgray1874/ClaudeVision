import argparse
from pathlib import Path

from config import DRAWINGS_DIR, ensure_directories
from file_scan import list_input_files, scan_file



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan drawings and build manufacturing/estimate inputs.")
    parser.add_argument("--pdf", type=str, help="Process a single PDF file.")
    parser.add_argument("--search-root", type=str, default=str(DRAWINGS_DIR), help="Folder to search for drawings.")
    parser.add_argument("--drawing-pattern", type=str, default="*.pdf", help="Glob pattern for drawings.")
    return parser.parse_args()



def main() -> None:
    args = parse_args()
    ensure_directories()

    if args.pdf:
        files = [Path(args.pdf)]
    else:
        files = list_input_files(Path(args.search_root), args.drawing_pattern)

    if not files:
        print(f"No PDF files found in {args.search_root if not args.pdf else args.pdf}")
        return

    print(f"Found {len(files)} PDF file(s).\n")

    for pdf_path in files:
        print(f"[SCAN] {pdf_path.name}")
        summary, output_paths = scan_file(pdf_path)

        print(f"Page count: {summary['page_count']}")
        print("Detected labels:", ", ".join(summary["detected_labels"]) or "None")
        print("Part numbers:", ", ".join(summary["pattern_summary"]["part_numbers"]) or "None")
        print("Dates:", ", ".join(summary["pattern_summary"]["dates"]) or "None")

        doc_analysis = summary.get("document_analysis", {})
        title_block = doc_analysis.get("title_block", {})
        print("Materials:", ", ".join(title_block.get("materials", [])) or "None")
        print("Surface finishes:", ", ".join(title_block.get("surface_finishes", [])) or "None")
        print("Colours:", ", ".join(title_block.get("colours", [])) or "None")
        print("Output files:")
        for output in output_paths:
            print(f"  - {output}")

        print("\nPart summaries:\n")
        estimate_lookup = {
            item["part_number"]: item for item in summary.get("estimate_summary", {}).get("part_estimates", [])
        }
        for part in summary["manufacturing_writeup"]["parts"]:
            estimate = estimate_lookup.get(part["part_number"], {})
            print(f"Part: {part['part_number']}")
            print(f"  Description: {part.get('description')}")
            print(f"  Quantity: {part.get('quantity')}")
            print(f"  Pages: {part.get('pages')}")
            print(f"  Materials: {', '.join(part.get('materials', [])) or 'None'}")
            print(f"  Finishes: {', '.join(part.get('surface_finishes', [])) or 'None'}")
            print(f"  Thicknesses: {', '.join([str(v) for v in part.get('thicknesses_mm', [])]) or 'None'}")
            print(f"  Angles: {', '.join([str(v) for v in part.get('angles_deg', [])]) or 'None'}")
            print(f"  Hole sizes: {', '.join([str(v) for v in part.get('hole_sizes_mm', [])]) or 'None'}")
            print(f"  Operations: {', '.join(part.get('textual_operations', [])) or 'None'}")
            print(f"  Geometry: {part.get('geometry_rollup')}")
            print(f"  Estimate: {estimate.get('estimated_total_cost_gbp')}")
            print()

        print("Manufacturing observations:")
        for observation in summary["manufacturing_writeup"]["manufacturing_observations"]:
            print(f"  - {observation}")

        total = summary.get("estimate_summary", {}).get("document_total_estimated_cost_gbp")
        print(f"\nEstimated document total: {total}")

        print("\nPage text preview:\n")
        for page in summary["pages"]:
            preview = (page["pdfplumber_text"] or "[NO TEXT EXTRACTED]").replace("\n", " ")
            print(f"Page {page['page_number']}: {preview[:500]}\n")


if __name__ == "__main__":
    main()
