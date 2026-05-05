import argparse
import json
from pathlib import Path

import config
from config import DRAWINGS_DIR, OUTPUT_DIR, ensure_directories
from estimate_template_parser import write_estimate_template_parse
from estimate_template_writeback import write_estimate_template_from_summary
from file_scan import list_input_files, scan_file
from historical_jobs import build_history_corpus
from rag_transformer import transform_scan_summary_to_historical_job_record
from sql_export import export_json_files_to_sqlserver_sql, export_single_json_file_to_sqlserver_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan drawings and build manufacturing and estimate inputs.")
    parser.add_argument("--pdf", type=str, help="Process a single PDF file.")
    parser.add_argument("--search-root", type=str, default=str(DRAWINGS_DIR), help="Folder to search for drawings.")
    parser.add_argument("--drawing-pattern", type=str, default="*.pdf", help="Glob pattern for drawings.")
    parser.add_argument("--build-history-corpus", action="store_true", help="Build a retrieval corpus from paired historical spreadsheets and drawings.")
    parser.add_argument("--transform-scan-json", type=str, help="Transform an existing scan JSON into a historical_job_record schema.")
    parser.add_argument("--parse-estimate-template", type=str, help="Parse an estimate workbook template and extract formula structures.")
    parser.add_argument("--write-estimate-template-from-json", type=str, help="Write estimate totals into a copy of the template workbook from a scan summary JSON.")
    parser.add_argument("--template-workbook", type=str, help="Template workbook path used for write-back (.xlsx required).")
    parser.add_argument("--output-workbook", type=str, help="Output workbook path for write-back result.")
    parser.add_argument("--export-json-to-sql", type=str, help="Export a single scan JSON file into one SQL Server insert script.")
    parser.add_argument("--export-json-dir-to-sql", type=str, help="Export all scan JSON files in a folder into one SQL Server insert script.")
    parser.add_argument("--sql-output", type=str, help="Optional output path for the generated SQL Server SQL script.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_directories()

    if args.build_history_corpus:
        result = build_history_corpus()
        print(f"Built history corpus for {result['job_count']} job(s).")
        print(f"JSON: {result['json_path']}")
        print(f"CSV: {result['csv_path']}")
        return

    if args.transform_scan_json:
        input_path = Path(args.transform_scan_json)
        with input_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
        record = transform_scan_summary_to_historical_job_record(summary)
        output_path = input_path.with_name(f"{input_path.stem}.historical_job_record.json")
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
        print(f"Historical job record written to: {output_path}")
        return

    if args.parse_estimate_template:
        workbook_path = Path(args.parse_estimate_template)
        output_path = workbook_path.with_name(f"{workbook_path.stem}.formula_parse.json")
        written = write_estimate_template_parse(workbook_path, output_path)
        print(f"Estimate template parse written to: {written}")
        return

    if args.write_estimate_template_from_json:
        json_path = Path(args.write_estimate_template_from_json)
        if not json_path.exists():
            print(f"JSON file not found: {json_path}")
            return
        template_path = Path(args.template_workbook) if args.template_workbook else Path(
            str(config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get("template_workbook", ""))
        )
        if not template_path.exists():
            print(f"Template workbook not found: {template_path}")
            return
        with json_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
        output_path = Path(args.output_workbook) if args.output_workbook else json_path.with_name(f"{json_path.stem}.estimate_writeback.xlsx")
        written = write_estimate_template_from_summary(summary, template_path, output_path)
        print(f"Estimate template write-back written to: {written}")
        print(f"Write-back audit JSON: {written.with_suffix('.writeback.audit.json')}")
        return

    if args.export_json_to_sql:
        json_path = Path(args.export_json_to_sql)
        if not json_path.exists():
            print(f"JSON file not found: {json_path}")
            return
        output_path = Path(args.sql_output) if args.sql_output else (OUTPUT_DIR / "sql" / f"{json_path.stem}.sql")
        written = export_single_json_file_to_sqlserver_sql(json_path, output_path)
        print(f"SQL Server export written to: {written}")
        print(f"JSON file included: {json_path.name}")
        return

    if args.export_json_dir_to_sql:
        json_dir = Path(args.export_json_dir_to_sql)
        json_files = sorted(path for path in json_dir.glob("*.json") if path.is_file())
        if not json_files:
            print(f"No JSON files found in {json_dir}")
            return
        output_path = Path(args.sql_output) if args.sql_output else (OUTPUT_DIR / "sql" / "drawing_scan_batch_export.sql")
        written = export_json_files_to_sqlserver_sql(json_files, output_path)
        print(f"SQL Server export written to: {written}")
        print(f"JSON files included: {len(json_files)}")
        return

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
        validation = summary.get("manufacturing_writeup", {}).get("validation", {})
        print("Validation status:", validation.get("status", "unknown"))
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
            print(f"  Page roles: {part.get('page_roles')}")
            print(f"  Materials: {', '.join(part.get('materials', [])) or 'None'}")
            print(f"  Finishes: {', '.join(part.get('surface_finishes', [])) or 'None'}")
            print(f"  Thicknesses: {', '.join([str(value) for value in part.get('thicknesses_mm', [])]) or 'None'}")
            print(f"  Angles: {', '.join([str(value) for value in part.get('angles_deg', [])]) or 'None'}")
            print(f"  Hole sizes: {', '.join([str(value) for value in part.get('hole_sizes_mm', [])]) or 'None'}")
            print(f"  Slot sizes: {', '.join([str(value) for value in part.get('slot_sizes_mm', [])]) or 'None'}")
            print(f"  Operations: {', '.join(part.get('textual_operations', [])) or 'None'}")
            print(f"  Process notes: {'; '.join(part.get('process_notes', [])) or 'None'}")
            print(f"  Geometry: {part.get('geometry_rollup')}")
            print(f"  Unit estimate: {estimate.get('unit_total_cost_gbp')}")
            print(f"  Extended estimate: {estimate.get('extended_total_cost_gbp')}")
            print()

        print("Manufacturing observations:")
        for observation in summary["manufacturing_writeup"]["manufacturing_observations"]:
            print(f"  - {observation}")

        if validation.get("issues"):
            print("\nValidation issues:")
            for issue in validation["issues"]:
                code = issue.get("code", "issue")
                reason = issue.get("reason", "")
                part = issue.get("part_number")
                prefix = f"{code} ({part})" if part else code
                print(f"  - {prefix}: {reason}")

        total = summary.get("estimate_summary", {}).get("document_total_estimated_cost_gbp")
        print(f"\nEstimated document total: {total}")

        print("\nPage text preview:\n")
        for page in summary["pages"]:
            preview = (page["pdfplumber_text"] or "[NO TEXT EXTRACTED]").replace("\n", " ")
            print(f"Page {page['page_number']} ({page.get('page_role', {}).get('primary_role', 'unknown')}): {preview[:500]}\n")


if __name__ == "__main__":
    main()
