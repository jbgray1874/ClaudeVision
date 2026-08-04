import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Load environment variables from .env file (project root: C:\ClaudeVision\.env)
# This makes XAI_API_KEY, OPENAI_API_KEY, etc. available without having to set
# them manually in each shell session. Must happen BEFORE any module that reads
# os.environ (note_scan, web_ai_price_lookup, etc.).
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        _load_dotenv(_env_path)
        print(f"[env] Loaded {_env_path}", flush=True)
    else:
        # Also try same directory as main.py (src/.env)
        _env_src = Path(__file__).resolve().parent / ".env"
        if _env_src.exists():
            _load_dotenv(_env_src)
            print(f"[env] Loaded {_env_src}", flush=True)
except ImportError:
    pass  # python-dotenv not installed — env vars must be set manually

# Windows consoles default to cp1252, which cannot encode characters like the
# warning sign (U+26A0). Any such print would raise UnicodeEncodeError and abort
# the run *before* the estimate xlsx is written. Force UTF-8 on the console
# streams so console output can never crash a scan.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from config import DRAWINGS_DIR, OUTPUT_DIR, ensure_directories
from estimate_parity_runner import build_part_metric_variance, write_parity_reports
from estimate_template_parser import write_estimate_template_parse
from estimate_full_parity_report import generate_and_write as generate_full_parity_reports, generate_bom_comparison_csv
from estimate_parity_pretty_report import generate_pretty_parity_html
from estimate_workbook_parity_report import build_report_rows as build_workbook_parity_rows, write_reports as write_workbook_parity_reports
from estimate_template_writeback import write_estimate_template_from_summary
from ai_spreadsheet_generator import generate_ai_estimating_spreadsheet
from drawing_job_merge import merge_dxf_into_json_file
from file_scan import group_input_files_by_folder, list_input_files, scan_file, scan_folder_job
from historical_jobs import build_history_corpus
from price_sources import reset_connectors
from pricing_service import PricingService
from rag_transformer import transform_scan_summary_to_historical_job_record
from sql_export import export_json_files_to_sqlserver_sql, export_single_json_file_to_sqlserver_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan drawings and build manufacturing and estimate inputs.")
    parser.add_argument("--pdf", type=str, help="Process a single drawing file (PDF or DXF).")
    parser.add_argument("--drawing", type=str, help="Alias for --pdf (PDF or DXF).")
    parser.add_argument(
        "--dxf",
        nargs="*",
        metavar="DXF_PATH",
        default=None,
        help=(
            "Flat-pattern DXF file(s) to attach to a PDF scan, or a GA DXF to scan standalone "
            "(omit --pdf for DXF-only). Same role as --attach-dxf but accepts multiple paths in one flag."
        ),
    )
    parser.add_argument("--search-root", type=str, default=str(DRAWINGS_DIR), help="Folder to search for drawings.")
    parser.add_argument("--drawing-pattern", type=str, default="*", help="Glob pattern for drawings (e.g. *.pdf, *.dxf).")
    parser.add_argument(
        "--attach-dxf",
        action="append",
        default=[],
        metavar="PATH",
        help="Flat-pattern DXF to merge into a PDF scan (repeatable). Join key: part number in filename.",
    )
    parser.add_argument(
        "--no-dxf-augment",
        action="store_true",
        help="Do not auto-discover flat DXFs beside the PDF / input/drawings/DXF when scanning a GA PDF.",
    )
    parser.add_argument(
        "--folder-as-job",
        action="store_true",
        help="Group all PDFs in each folder into one pooled BOM + single bay estimate (overrides config default).",
    )
    parser.add_argument(
        "--no-folder-as-job",
        action="store_true",
        help="Scan each PDF separately even when config folder_as_job is enabled.",
    )
    parser.add_argument(
        "--merge-dxf-into",
        type=str,
        help="Augment an existing scan JSON with flat DXF geometry, then re-estimate (use with --dxf-glob or --attach-dxf).",
    )
    parser.add_argument(
        "--dxf-glob",
        type=str,
        help="Glob of flat DXFs for --merge-dxf-into (relative to cwd or absolute).",
    )
    parser.add_argument("--build-history-corpus", action="store_true", help="Build a retrieval corpus from paired historical spreadsheets and drawings.")
    parser.add_argument("--transform-scan-json", type=str, help="Transform an existing scan JSON into a historical_job_record schema.")
    parser.add_argument("--parse-estimate-template", type=str, help="Parse an estimate workbook template and extract formula structures.")
    parser.add_argument("--write-estimate-template-from-json", type=str, help="Write estimate totals into a copy of the template workbook from a scan summary JSON.")
    parser.add_argument("--template-workbook", type=str, help="Template workbook path used for write-back (.xlsx required).")
    parser.add_argument("--output-workbook", type=str, help="Output workbook path for write-back result.")
    parser.add_argument("--estimate-workbook-parity-report", type=str, help="Generate mapped-cell parity report from summary JSON against workbook cells.")
    parser.add_argument("--parity-workbook", type=str, help="Workbook path for parity report.")
    parser.add_argument("--parity-sheet", type=str, default="Estimate", help="Sheet name for parity report.")
    parser.add_argument("--parity-out-csv", type=str, help="Output CSV path for parity report.")
    parser.add_argument("--parity-out-json", type=str, help="Output JSON path for parity report.")
    parser.add_argument(
        "--estimate-full-parity-report",
        type=str,
        help="Full workbook vs scan JSON parity (totals + labour route + provenance bundle). .xlsx uses openpyxl unless --full-parity-read-via-excel.",
    )
    parser.add_argument("--full-parity-out-json", type=str, help="Output JSON bundle for full parity.")
    parser.add_argument("--full-parity-out-csv", type=str, help="Flattened CSV for full parity.")
    parser.add_argument(
        "--full-parity-read-via-excel",
        action="store_true",
        help="Windows: read workbook values through Excel COM (pywin32) so formulas are calculated even when the file cache is empty.",
    )
    parser.add_argument(
        "--pretty-report",
        action="store_true",
        help="With --estimate-full-parity-report: also write a standalone HTML dashboard (Tailwind+Chart.js CDN).",
    )
    parser.add_argument(
        "--pretty-report-out",
        type=str,
        help="Output path for HTML dashboard (default: next to full parity JSON with .parity.html).",
    )
    parser.add_argument(
        "--bom-comparison-out",
        type=str,
        help="With --estimate-full-parity-report: BOM + labour comparison CSV path (default: same folder as full parity CSV, {summary stem}.bom_comparison.csv).",
    )
    parser.add_argument("--export-json-to-sql", type=str, help="Export a single scan JSON file into one SQL Server insert script.")
    parser.add_argument("--export-json-dir-to-sql", type=str, help="Export all scan JSON files in a folder into one SQL Server insert script.")
    parser.add_argument("--sql-output", type=str, help="Optional output path for the generated SQL Server SQL script.")
    parser.add_argument("--price-from-json", type=str, help="Run UDEF-first pricing service on a normalized/scan JSON file.")
    parser.add_argument("--price-out-json", type=str, help="Output JSON path for priced estimate.")
    parser.add_argument("--historical-top-k", type=int, default=5, help="Top-k historical matches per part in priced output.")
    parser.add_argument("--estimate-parity-expected-json", type=str, help="Expected estimate JSON for parity run.")
    parser.add_argument("--estimate-parity-actual-json", type=str, help="Actual estimate JSON for parity run.")
    parser.add_argument("--estimate-parity-out-csv", type=str, help="Output CSV path for estimate parity.")
    parser.add_argument("--estimate-parity-out-json", type=str, help="Output JSON path for estimate parity.")
    parser.add_argument(
        "--enable-web-ai-pricing-fallback",
        action="store_true",
        help=(
            "When internal SQL / spreadsheet / catalogue miss a price, allow WebPriceConnector LLM market "
            "estimates (requires web.enabled + XAI_API_KEY or OPENAI_API_KEY; uses API tokens)."
        ),
    )
    parser.add_argument(
        "--generate-ai-spreadsheet",
        action="store_true",
        help="After each PDF scan, write AI_Estimate_<stem>.xlsx using estimate template write-back (.xlsx template required).",
    )
    parser.add_argument(
        "--ai-spreadsheet-template",
        type=str,
        help="Optional .xlsx template path for --generate-ai-spreadsheet (default: config.AI_ESTIMATE_XLSX_TEMPLATE or .xlsx beside the blank .xls).",
    )
    parser.add_argument(
        "--ai-spreadsheet-out",
        type=str,
        help="Optional output .xlsx path for --generate-ai-spreadsheet.",
    )
    parser.add_argument(
        "--deliverables",
        action="store_true",
        help="After populate, generate client quote (always) + parity report (if a manual estimate is found).",
    )
    parser.add_argument(
        "--order-qty", type=int, default=None,
        help="Order/demand quantity for this job (drives batch economics + the WB order qty). "
             "Each tender product prices at its own demand qty. If omitted, the engine's "
             "inferred/assumed quantity is used.",
    )
    parser.add_argument(
        "--customer", type=str, default=None,
        help="Customer name for the quote/report header (e.g. \"M&S\"). Authoritative — "
             "overrides the folder/path heuristic. Also the logo key (assets/customer_logos/<name>).",
    )
    return parser.parse_args()


def _apply_web_ai_pricing_fallback_from_args(args: argparse.Namespace) -> None:
    if not getattr(args, "enable_web_ai_pricing_fallback", False):
        return
    pol = dict(getattr(config, "FALLBACK_PRICING_POLICY", None) or {})
    pol["enable_web_ai_fallback"] = True
    config.FALLBACK_PRICING_POLICY = pol
    price_cfg = dict(config.PRICE_SOURCE_CONFIG)
    web = dict(price_cfg.get("web") or {})
    web["enabled"] = True
    web.setdefault("llm_market_estimate_fallback", True)
    price_cfg["web"] = web
    config.PRICE_SOURCE_CONFIG = price_cfg


def main() -> None:
    args = parse_args()
    ensure_directories()

    # THE ORDER QUANTITY HAS TO ARRIVE BEFORE THE COSTING, NOT AFTER IT.
    #
    # --order-qty was stamped onto the summary once scan_file had already returned, and by
    # then estimate_document had costed every part with `assumed_job_quantity`, which
    # file_scan defaults to DEFAULT_JOB_QUANTITY when the enquiry does not state one. Setup
    # is amortised as (rate/60 x setup_mins) / qty, so a 10-off job was priced with its
    # setup spread over 180 units and then labelled "10" on the header — the flag whose own
    # help text says it "drives batch economics" reached everything except the economics.
    #
    # Published as an environment variable rather than threaded through a parameter because
    # three scan entry points share one finalizer, and because the intranet integration
    # calls file_scan directly without going through this CLI at all. One place decides the
    # quantity; everything downstream reads what it decided.
    if getattr(args, "order_qty", None):
        os.environ["SDI_ORDER_QTY"] = str(int(args.order_qty))

    if args.merge_dxf_into:
        json_path = Path(args.merge_dxf_into)
        dxf_paths: list[Path] = [Path(d) for d in (args.dxf or [])] + [Path(p) for p in (args.attach_dxf or [])]
        if args.dxf_glob:
            dxf_paths.extend(sorted(Path().glob(args.dxf_glob)))
        if not dxf_paths:
            print("No DXF files: pass --attach-dxf and/or --dxf-glob")
            return
        out = Path(args.price_out_json) if args.price_out_json else json_path
        written = merge_dxf_into_json_file(json_path, dxf_paths, output_path=out, reestimate=True)
        print(f"Merged DXF geometry into: {written}")
        aug = {}
        try:
            with written.open("r", encoding="utf-8") as handle:
                aug = json.load(handle).get("dxf_augmentation", {})
        except Exception:
            pass
        print(f"Matched: {len(aug.get('matched', []))}  Unmatched DXF: {len(aug.get('unmatched_dxf', []))}")
        return

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

    if args.estimate_full_parity_report:
        summary_path = Path(args.estimate_full_parity_report)
        if not summary_path.exists():
            print(f"JSON file not found: {summary_path}")
            return
        wb_path = Path(args.parity_workbook) if args.parity_workbook else Path(
            str(config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get("template_workbook", ""))
        )
        if not wb_path.exists():
            print(f"Workbook for full parity report not found: {wb_path}")
            return
        out_j = Path(args.full_parity_out_json) if args.full_parity_out_json else (
            OUTPUT_DIR / "csv" / f"{summary_path.stem}.full_parity.bundle.json"
        )
        out_c = Path(args.full_parity_out_csv) if args.full_parity_out_csv else (
            OUTPUT_DIR / "csv" / f"{summary_path.stem}.full_parity.flat.csv"
        )
        bundle, out_j_written, out_c_written = generate_full_parity_reports(
            summary_path,
            wb_path,
            out_j,
            out_c,
            read_via_excel=bool(args.full_parity_read_via_excel),
        )
        print(json.dumps(bundle.get("status_counts") or {}, indent=2))
        print(f"Full parity bundle JSON: {out_j_written.resolve()}")
        print(f"Full parity flat CSV: {out_c_written.resolve()}")
        with summary_path.open("r", encoding="utf-8") as handle:
            summary_obj = json.load(handle)
        bom_out = Path(args.bom_comparison_out) if args.bom_comparison_out else out_c_written.with_name(
            f"{summary_path.stem}.bom_comparison.csv"
        )
        bom_path = generate_bom_comparison_csv(summary_obj, bom_out)
        print(f"BOM comparison CSV: {bom_path}")
        if args.pretty_report:
            out_html = Path(args.pretty_report_out) if args.pretty_report_out else out_j.with_suffix(".parity.html")
            html_written = generate_pretty_parity_html(bundle=bundle, summary=summary_obj, output_path=out_html)
            print(f"Parity HTML dashboard: {html_written}")
        return

    if args.estimate_workbook_parity_report:
        summary_path = Path(args.estimate_workbook_parity_report)
        if not summary_path.exists():
            print(f"JSON file not found: {summary_path}")
            return
        wb_path = Path(args.parity_workbook) if args.parity_workbook else Path(
            str(config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get("template_workbook", ""))
        )
        if not wb_path.exists():
            print(f"Workbook for parity report not found: {wb_path}")
            return
        with summary_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
        rows = build_workbook_parity_rows(summary, wb_path, sheet_name=args.parity_sheet)
        out_csv = Path(args.parity_out_csv) if args.parity_out_csv else (OUTPUT_DIR / "csv" / f"{summary_path.stem}.workbook_parity.csv")
        out_json = Path(args.parity_out_json) if args.parity_out_json else (OUTPUT_DIR / "csv" / f"{summary_path.stem}.workbook_parity.json")
        write_workbook_parity_reports(rows, out_csv, out_json)
        print(f"Workbook parity CSV: {out_csv}")
        print(f"Workbook parity JSON: {out_json}")
        print(f"Parity rows: {len(rows)}")
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

    if args.price_from_json:
        input_path = Path(args.price_from_json)
        if not input_path.exists():
            print(f"JSON file not found: {input_path}")
            return
        with input_path.open("r", encoding="utf-8") as handle:
            drawing_json = json.load(handle)
        engine = PricingService()
        priced = engine.calculate_estimate(drawing_json, historical_top_k=args.historical_top_k)
        out_json = Path(args.price_out_json) if args.price_out_json else (OUTPUT_DIR / "json" / f"{input_path.stem}.priced_estimate.json")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        with out_json.open("w", encoding="utf-8") as handle:
            json.dump(priced, handle, indent=2, ensure_ascii=False)
        print(f"Priced estimate JSON: {out_json}")
        print(f"Parts priced: {len(priced.get('parts', []))}")
        return

    if args.estimate_parity_expected_json and args.estimate_parity_actual_json:
        expected_path = Path(args.estimate_parity_expected_json)
        actual_path = Path(args.estimate_parity_actual_json)
        if not expected_path.exists():
            print(f"Expected JSON not found: {expected_path}")
            return
        if not actual_path.exists():
            print(f"Actual JSON not found: {actual_path}")
            return
        with expected_path.open("r", encoding="utf-8") as handle:
            expected = json.load(handle)
        with actual_path.open("r", encoding="utf-8") as handle:
            actual = json.load(handle)
        rows = build_part_metric_variance(expected, actual)
        out_csv = Path(args.estimate_parity_out_csv) if args.estimate_parity_out_csv else (OUTPUT_DIR / "csv" / f"{actual_path.stem}.estimate_parity.csv")
        out_json = Path(args.estimate_parity_out_json) if args.estimate_parity_out_json else (OUTPUT_DIR / "csv" / f"{actual_path.stem}.estimate_parity.json")
        write_parity_reports(rows, out_csv, out_json)
        print(f"Estimate parity CSV: {out_csv}")
        print(f"Estimate parity JSON: {out_json}")
        print(f"Parity rows: {len(rows)}")
        return

    drawing_arg = args.pdf or args.drawing
    dxf_from_cli = [Path(d) for d in (args.dxf or [])] + [Path(p) for p in (args.attach_dxf or [])]

    if drawing_arg:
        files = [Path(drawing_arg)]
    elif dxf_from_cli:
        files = [dxf_from_cli[0]]
    else:
        files = list_input_files(Path(args.search_root), args.drawing_pattern)

    if not files:
        target = drawing_arg or (str(dxf_from_cli[0]) if dxf_from_cli else args.search_root)
        print(f"No drawing files found in {target}")
        return

    print(f"Found {len(files)} drawing file(s).\n")

    _apply_web_ai_pricing_fallback_from_args(args)

    auto_discover_dxf = not args.no_dxf_augment
    dxf_only_primary = bool(dxf_from_cli and not drawing_arg)
    job_cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    folder_as_job = bool(job_cfg.get("folder_as_job", False))
    if args.folder_as_job:
        folder_as_job = True
    if args.no_folder_as_job:
        folder_as_job = False

    scan_jobs: List[Tuple[Optional[Path], List[Path]]] = []
    if folder_as_job and not drawing_arg and not dxf_only_primary:
        groups = group_input_files_by_folder(files)
        scan_jobs = [(folder, pdfs) for folder, pdfs in sorted(groups.items()) if pdfs]
        print(f"Folder-as-job: {len(scan_jobs)} job folder(s) from {len(files)} file(s).\n")
    else:
        scan_jobs = [(None, [path]) for path in files]

    for job_folder, job_files in scan_jobs:
        reset_connectors()
        if job_folder is not None:
            print(f"[JOB] {job_folder.name} ({len(job_files)} PDF(s))")
            # BEFORE ANYTHING READS THE FOLDER, MAKE WHAT WE CAN READABLE. A DWG is a DXF in
            # a different container — the same measured outline — and it was being ignored,
            # so those parts were sized from drawing text while their geometry sat unopened.
            # Converting first means the DXFs it produces are discovered by the ordinary
            # scan, with no special path for them afterwards.
            #
            # Never allowed to stop a job: a folder with no DWGs, no converter installed, or
            # a converter that fails, all end the same way — the estimate runs exactly as it
            # does today and the report says what was not used.
            _cad_conv, _cad_inv = {}, {}
            try:
                import cad_inputs
                _cad_conv = cad_inputs.convert_dwgs(job_folder)
                if _cad_conv.get("converted"):
                    print(f"   [cad] converted {len(_cad_conv['converted'])} DWG(s) to DXF")
                if _cad_conv.get("reason"):
                    print(f"   [cad] {_cad_conv['reason']}")
                _cad_inv = cad_inputs.inventory(
                    job_folder, converted=_cad_conv.get("converted_paths") or [])
                if _cad_inv.get("unread"):
                    print(f"   [cad] {len(_cad_inv['unread'])} file(s) present and not read: "
                          f"{', '.join(_cad_inv['unread'][:6])}")
            except Exception as _exc:
                print(f"   [cad] input inventory skipped ({_exc})")

            # Handed over explicitly rather than left to be discovered. Folder discovery
            # globs the job folder and a "DXF" subfolder only — it does not recurse — so a
            # converted file written anywhere else would be produced and then never read,
            # which looks exactly like the feature working.
            #
            # HELD TO THE SAME STANDARD AS A SUPPLIED FILE. attach_dxf_paths deliberately
            # skips the flat-part filter, because a human naming a file has already made that
            # judgement. Nobody made it here: a job folder's DWGs are whatever the customer
            # sent, and a converted GA sheet handed over unfiltered would be read as a part's
            # flat pattern. Discovery's own predicate decides, so a converted file is judged
            # exactly as the same file would be if it had arrived as a DXF.
            _converted_dxf = [Path(p) for p in (_cad_conv.get("converted_paths") or [])]
            try:
                from drawing_job_merge import is_flat_part_dxf
                _rejected = [p for p in _converted_dxf if not is_flat_part_dxf(p)]
                _converted_dxf = [p for p in _converted_dxf if is_flat_part_dxf(p)]
                if _rejected:
                    print(f"   [cad] {len(_rejected)} converted DXF(s) are not part flat "
                          f"patterns (GA sheets or no part number in the name) and were not "
                          f"used for geometry: {', '.join(p.name for p in _rejected[:4])}")
            except ImportError:
                pass
            summary, output_paths = scan_folder_job(
                job_folder,
                job_files,
                attach_dxf_paths=_converted_dxf or None,
                auto_discover_dxf=auto_discover_dxf,
            )
            # Stamped onto the job so the report, the quote gate and the re-check CLI all
            # read the same record of what was supplied and what was done with it.
            if isinstance(summary, dict):
                if _cad_inv:
                    summary["cad_inputs"] = _cad_inv
                if _cad_conv.get("found"):
                    summary["dwg_conversion"] = _cad_conv
            scan_label = job_folder.name
        else:
            drawing_path = job_files[0]
            print(f"[SCAN] {drawing_path.name}")
            if drawing_arg:
                attach_dxf = dxf_from_cli or None
                discover = auto_discover_dxf
            elif dxf_only_primary:
                attach_dxf = dxf_from_cli[1:] or None
                discover = False
            else:
                attach_dxf = None
                discover = auto_discover_dxf

            summary, output_paths = scan_file(
                drawing_path,
                attach_dxf_paths=attach_dxf,
                auto_discover_dxf=discover,
            )
            scan_label = drawing_path.name

        # SDI Intelligence — Learning Engine
        try:
            from learning_engine import get_engine
            summary = get_engine().post_scan(summary)
        except Exception:
            pass

        # Explicit order quantity (--order-qty), onto the fields the JOB-LEVEL additions read.
        #
        # The costing itself has already happened at this quantity — SDI_ORDER_QTY is set
        # before the scan and file_scan decides the number once, before estimate_document.
        # What remains here is stamping the same value on the estimate_summary node that
        # wb_populate reads for the order-qty cell, and on summary["quantity"] which the
        # assembly-labour calc below reads. It agrees with the costing rather than replacing
        # it; check_the_quantity_costed_is_the_quantity_ordered blocks the job if it ever
        # does not, so this can no longer paper over a batch the parts were not priced for.
        if getattr(args, "order_qty", None):
            try:
                _oq = int(args.order_qty)
                summary["quantity"] = _oq
                summary["assumed_job_quantity"] = _oq
                _esd = summary.get("estimate_summary")
                if isinstance(_esd, dict):
                    _esd["assumed_job_quantity"] = _oq
                print(f"  Order quantity set to {_oq} (from --order-qty)")
            except Exception:
                pass

        # Deterministic drawing-facts enrichment (Layer 2) — GATED (SDI_APPLY_DRAWING_FACTS) and
        # non-destructive: fills material/finish only where the engine has none, and surfaces the
        # printed weights + tube stock as review flags. Safe on DXF/native jobs (those layers
        # already fill these, so nothing is overwritten). For no-DXF customer tender drawings it
        # is the trustworthy backbone. Off by default so proven jobs (12120/1282) are untouched.
        import os as _os_df
        if _os_df.getenv("SDI_APPLY_DRAWING_FACTS", "").lower() in {"1", "true", "yes"}:
            try:
                from drawing_facts import extract_drawing_facts
                from source_connectors.drawing_facts_conn import apply_drawing_facts_to_part_estimates
                _dp = job_files[0] if job_files else None
                _dps = str(_dp) if _dp else ""
                if _dps.lower().endswith(".pdf"):
                    _facts = extract_drawing_facts(_dps)
                    _sb = _facts.get("spec_block") or {}
                    _cnt = apply_drawing_facts_to_part_estimates(summary, _facts)
                    summary.setdefault("drawing_facts", {})["spec_block"] = _sb
                    print(f"  [drawing-facts] material+{_cnt['material_set']} finish+{_cnt['finish_set']} "
                          f"weight+{_cnt['weight_flagged']} tube+{_cnt['tube_flagged']} "
                          f"weld-flag+{_cnt.get('weld_flagged', 0)} | "
                          f"powder={_sb.get('powder_micron')}um weld={_sb.get('weld_spec')}")
            except Exception as _exc:
                print(f"  [drawing-facts] skipped ({_exc})")

        # ── Job-level additions: assembly labour (history) + bought-in materials (Tim BOM) ──
        # Computed AFTER the scan, then folded into BOTH the bay estimate AND the canonical
        # estimate_summary (workbook_equivalent_pricing / cost_breakdown / document total). The
        # saved JSON is then RE-WRITTEN, so the spreadsheet, JSON and parity report all agree.
        _assembly_cost = 0.0
        _bought_in_total = 0.0
        _es = summary.get("estimate_summary", {}) or {}
        _bay = summary.get("bay_estimate")
        try:
            from pricing_service import PricingService as _PS
            _qty = int(summary.get("quantity") or _es.get("assumed_job_quantity") or 1)
            _asm = _PS().estimate_assembly_pack_labour(quantity=_qty)
            _assembly_cost = float(_asm.get("cost_per_bay_gbp") or 0.0)
            if isinstance(_bay, dict):
                _bay["assembly_pack_labour"] = _asm
            print(f"  Assembly/pack labour: \u00a3{_assembly_cost:.2f}/bay ({_asm.get('basis')})"
                  + (f" \u2014 {_asm['flag']}" if _asm.get("flag") else ""))
        except Exception as _exc:
            print(f"  (assembly labour estimate skipped: {_exc})")
        # FIX 3: prefer Tim's INGESTED per-drawing assemble/pack labour over the E2 median.
        # Same learn-from-Tim pattern as bought-in / rate-card; E2 median stays the fallback
        # for novel jobs with no ingested assembly line.
        try:
            import os as _os_al, json as _json_al, re as _re_al
            _alp = _os_al.path.join(_os_al.path.dirname(_os_al.path.abspath(__file__)), "job_assembly_labour.json")
            if _os_al.path.exists(_alp):
                with open(_alp) as _fh_al:
                    _almap = (_json_al.load(_fh_al) or {}).get("by_drawing", {})
                def _norm_al(v):
                    _mm = _re_al.match(r"\s*(\d+)", str(v or ""))
                    return _mm.group(1) if _mm else ""
                _alkey = _norm_al(scan_label) or _norm_al(summary.get("job_number"))
                _al = next((v for k, v in _almap.items() if _norm_al(k) and _norm_al(k) == _alkey), None)
                _al_total = float((_al or {}).get("total_gbp") or 0.0)
                if _al and _al_total:
                    _assembly_cost = _al_total
                    if isinstance(_bay, dict):
                        _bay["assembly_pack_labour"] = {
                            "cost_per_bay_gbp": _al_total,
                            "basis": "tim_ingested_per_drawing",
                            "source": _al.get("source"),
                            "lines": _al.get("lines", []),
                            "flag": None,
                        }
                    print(f"  Assembly/pack labour (Tim ingest): \u00a3{_al_total:.2f}/bay "
                          f"({len(_al.get('lines', []))} lines) \u2014 overrides E2 median")
        except Exception as _exc_al:
            print(f"  (assembly ingest skipped: {_exc_al})")
        try:
            import os as _os_bi, json as _json_bi, re as _re_bi
            _bip = _os_bi.path.join(_os_bi.path.dirname(_os_bi.path.abspath(__file__)), "job_bought_in_materials.json")
            if _os_bi.path.exists(_bip):
                with open(_bip) as _fh_bi:
                    _bimap = (_json_bi.load(_fh_bi) or {}).get("by_drawing", {})
                def _norm_bi(v):
                    _mm = _re_bi.match(r"\s*(\d+)", str(v or ""))
                    return _mm.group(1) if _mm else ""
                _key = _norm_bi(scan_label) or _norm_bi(summary.get("job_number"))
                _bi = next((v for k, v in _bimap.items() if _norm_bi(k) and _norm_bi(k) == _key), None)
                _bought_in_total = float((_bi or {}).get("total_gbp") or 0.0)
                if _bi and isinstance(_bay, dict) and _bought_in_total:
                    _bay["bought_in_materials"] = _bi
                    print(f"  Bought-in materials: \u00a3{_bought_in_total:.2f}/bay "
                          f"({len(_bi.get('lines', []))} lines, from {_bi.get('source')})")
        except Exception as _exc_bi:
            print(f"  (bought-in materials skipped: {_exc_bi})")

        # Fold both into the canonical totals + bay, then RE-WRITE the saved JSON so
        # --estimate-full-parity-report (which reads m59_material_subtotal_gbp etc.) agrees.
        if _assembly_cost or _bought_in_total:
            try:
                from estimator import _build_workbook_equivalent_pricing as _bwep
                _wep = _es.get("workbook_equivalent_pricing") or {}
                _parts = _es.get("part_estimates") or []
                _new_mat = round(float(_wep.get("m59_material_subtotal_gbp") or 0.0) + _bought_in_total, 4)
                _new_lab = round(float(_wep.get("m103_labour_subtotal_gbp") or 0.0) + _assembly_cost, 4)
                if _parts:
                    _es["workbook_equivalent_pricing"] = _bwep(_parts, material_total=_new_mat, labour_total=_new_lab)
                _cb = _es.get("cost_breakdown") or {}
                if isinstance(_cb.get("material"), dict):
                    _cb["material"]["total"] = _new_mat
                if isinstance(_cb.get("labour"), dict):
                    _cb["labour"]["total"] = _new_lab
                _delta = round(_bought_in_total + _assembly_cost, 2)
                for _df in ("document_total_estimated_cost_gbp", "document_total_raw_gbp"):
                    if isinstance(_es.get(_df), (int, float)):
                        _es[_df] = round(_es[_df] + _delta, 2)
                _hcp = (_es.get("historical_comparison_projection") or {}).get("totals")
                if isinstance(_hcp, dict):
                    _hcp["material_subtotal_gbp"] = _new_mat
                    _hcp["labour_subtotal_gbp"] = _new_lab
                    if isinstance(_hcp.get("document_total_estimated_cost_gbp"), (int, float)):
                        _hcp["document_total_estimated_cost_gbp"] = round(_hcp["document_total_estimated_cost_gbp"] + _delta, 2)
                    _m105_rec = float((_es.get("workbook_equivalent_pricing") or {}).get("m105_total_unit_cost_gbp") or 0.0)
                    if _m105_rec and isinstance(_hcp.get("workbook_equivalent_total_unit_cost_gbp"), (int, float)):
                        _hcp["workbook_equivalent_total_unit_cost_gbp"] = round(_m105_rec, 4)
                # data_sufficiency + provisional totals were frozen BEFORE this reconciliation;
                # bring them up to the reconciled figure so every document-total field agrees
                # (otherwise the spreadsheet headline + parity report read the stale fabricated-only number).
                _ds = _es.get("data_sufficiency")
                if isinstance(_ds, dict):
                    for _dk in ("document_total_provisional_gbp", "document_total_reportable_gbp"):
                        if isinstance(_ds.get(_dk), (int, float)):
                            _ds[_dk] = round(_ds[_dk] + _delta, 2)
                if isinstance(_es.get("document_total_provisional_gbp"), (int, float)):
                    _es["document_total_provisional_gbp"] = round(_es["document_total_provisional_gbp"] + _delta, 2)
                if isinstance(_bay, dict):
                    for _k in ("bay_unit_total_provisional_gbp", "bay_unit_total_confident_gbp"):
                        if isinstance(_bay.get(_k), (int, float)):
                            _bay[_k] = round(_bay[_k] + _delta, 2)
                    _pkg = float(((_bay.get("packaging") or {}).get("packaging_cost_per_bay_gbp")) or 0.0)
                    _mfg = float(_bay.get("bay_unit_total_provisional_gbp") or 0.0)
                    _opct = float(_bay.get("overhead_pct_applied") or 0.0)
                    _ovh = round((_mfg + _pkg) * _opct / 100.0, 2)
                    _bay["overhead_gbp"] = _ovh
                    _bay["bay_sell_total_gbp"] = round(_mfg + _pkg + _ovh, 2)
                _canon = (summary.get("saved_output_paths") or {}).get("json")
                if _canon and Path(_canon).exists():
                    try:
                        from file_scan import _json_default as _jd
                    except Exception:
                        _jd = str
                    with open(_canon, "w", encoding="utf-8") as _fh_rw:
                        json.dump(summary, _fh_rw, indent=2, ensure_ascii=False, default=_jd)
                    print(f"  Reconciled JSON re-written (material +\u00a3{_bought_in_total:.2f}, labour +\u00a3{_assembly_cost:.2f})")
            except Exception as _exc_rc:
                print(f"  (totals reconciliation skipped: {_exc_rc})")

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
            geom_src = part.get("geometry_source") or "pdf"
            geom_rel = (part.get("geometry_rollup", {}).get("confidence") or {}).get("geometry_reliability")
            print(f"  Geometry source: {geom_src}  reliability: {geom_rel}")
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

        aug = summary.get("dxf_augmentation") or {}
        if aug:
            print(f"\nDXF augmentation: matched {len(aug.get('matched', []))}, "
                  f"unmatched DXF {len(aug.get('unmatched_dxf', []))}, "
                  f"skipped {len(aug.get('skipped', []))}")

        total = summary.get("estimate_summary", {}).get("document_total_estimated_cost_gbp")
        ds = (summary.get("estimate_summary") or {}).get("data_sufficiency") or {}
        if ds.get("status") == "insufficient_data":
            prov = ds.get("document_total_provisional_gbp")
            print(f"\n⚠  INSUFFICIENT DATA — part DXFs required for credible auto-estimate")
            print(f"   Provisional computed total £{prov:,.2f} is NOT reportable "
                  f"(credible {ds.get('credible_cost_ratio', 0) * 100:.0f}% · "
                  f"DXF on {ds.get('dxf_part_ratio', 0) * 100:.0f}% of fabricated parts)")
        else:
            print(f"\nEstimated document total: {total}")

        if getattr(args, "generate_ai_spreadsheet", False):
            try:
                tpl = Path(args.ai_spreadsheet_template) if args.ai_spreadsheet_template else None
                out_xlsx = Path(args.ai_spreadsheet_out) if args.ai_spreadsheet_out else None
                ai_path = generate_ai_estimating_spreadsheet(summary, template_path=tpl, output_path=out_xlsx)
                print(f"\nAI estimating spreadsheet: {ai_path.resolve()}")
            except Exception as exc:
                print(f"\nAI estimating spreadsheet failed: {exc}", flush=True)

        # Auto-generate clean BOM/Routes/Summary xlsx on every scan
        # ── AI Estimate Sheet (wb_populate — primary output) ──────────────
        # Populates the estimators' real Blank Estimating Workbook template
        # and lets its own formulas compute material + labour → sell price.
        # Falls back to the old xlsx_output builder if the template is
        # unreachable (e.g. share unavailable), so a network blip doesn't
        # stop the run.
        xlsx_path = None
        try:
            from wb_populate import populate_workbook
            xlsx_path = populate_workbook(summary, str(scan_label))
            if xlsx_path:
                print(f"\nAI Estimate Sheet: {Path(xlsx_path).resolve()}")
                # Stamp the workbook's ACCEPTED labour rows into the canonical JSON.
                # The JSON is written earlier in the run, before the workbook exists, so
                # without this the route record populate_workbook builds never reaches the
                # deliverables — which read the saved file, not this in-memory summary. They
                # would fall back to the engine-side costed fields, which are PRE-filter and
                # still carry powder on timber and weld on artefact records. Same principle
                # as the wep-readback below: the workbook is the authority, so what it
                # accepted has to come back.
                try:
                    from costed_facts import reconcile_risk_flags as _rrf
                    _wl = summary.get("workbook_labour")
                    _canon_wl = (summary.get("saved_output_paths") or {}).get("json")
                    # Reconcile the IN-MEMORY summary first: the Decision Report and AI
                    # Provenance sheets are written from it a few lines below.
                    _rc_mem = _rrf(summary)
                    if _wl and _canon_wl and Path(_canon_wl).exists():
                        with open(_canon_wl, encoding="utf-8") as _fh_r:
                            _doc = json.load(_fh_r)
                        _doc["workbook_labour"] = _wl
                        # THE CANONICAL PART LIST HAS TO REACH THE FILE, NOT JUST THIS RUN.
                        #
                        # populate_workbook stamps it onto the in-memory summary, and the
                        # two workbook tabs are written from that — so they were right. The
                        # quote and job report are generated from the SAVED JSON
                        # (_gen_job_report takes a path, not an object), which was written
                        # before the workbook existed and never received it. Both fell back
                        # to raw part_estimates, which is the exact divergence the shared
                        # list exists to close: merged duplicates back, rolled quantities
                        # gone, and the bought-in BOM lines the sheet charges missing again.
                        _canon_pes = ((summary.get("estimate_summary") or {})
                                      .get("canonical_part_estimates"))
                        if isinstance(_canon_pes, list) and _canon_pes:
                            ((_doc.setdefault("estimate_summary", {}))
                             ["canonical_part_estimates"]) = _canon_pes
                        if _wl.get("mode") == "canonical":
                            ((_doc.setdefault("estimate_summary", {}))
                             .setdefault("canonical_route_shadow", {}))["mode"] = "cutover"
                        # ...and the on-disk copy, which is what the HTML deliverables read.
                        # Both must agree or the .xlsx tabs and the HTML diverge again.
                        _rc_doc = _rrf(_doc)
                        with open(_canon_wl, "w", encoding="utf-8") as _fh_w:
                            json.dump(_doc, _fh_w, indent=2, ensure_ascii=False, default=str)
                        if _rc_doc.get("superseded") or _rc_mem.get("superseded"):
                            print(f"   [risk-flags] {max(_rc_doc.get('superseded', 0), _rc_mem.get('superseded', 0))} "
                                  f"flag(s) superseded — the drawing cue was read but the "
                                  f"priced route has no such operation; recorded on the part "
                                  f"as superseded_risk_flags, not dropped", flush=True)
                        print(f"   [workbook-route] {len(_wl.get('rows') or [])} accepted "
                              f"labour row(s) stamped into the JSON — quote, report and "
                              f"Decision Report now describe the priced route", flush=True)
                except Exception as _wl_exc:
                    print(f"   [workbook-route] not stamped ({_wl_exc}) — deliverables will "
                          f"fall back to PRE-FILTER engine ops and may name operations the "
                          f"sheet does not charge", flush=True)
            else:
                raise RuntimeError("populate_workbook returned None")
        except Exception as _wb_exc:
            print(f"\n[wb_populate] failed ({_wb_exc})", flush=True)
            # Full traceback so the failing line is visible, not just the message.
            # A bare exception message (e.g. a KeyError with only a key name) hides
            # where in populate_workbook's 400+ lines it died; the fallback to the
            # old builder is otherwise silent about the real cause.
            import traceback as _tb
            print("   [wb_populate] traceback:", flush=True)
            _tb.print_exc()
            try:
                from config import CANONICAL_ROUTE_WORKBOOK_CUTOVER as _canonical_cutover
            except Exception:
                _canonical_cutover = False
            if _canonical_cutover:
                print("   -> NO fallback workbook written: canonical route cutover is "
                      "enabled, and the legacy builder can resurrect or multiply rejected "
                      "operations. Fix the canonical failure and re-run.", flush=True)
            else:
                try:
                    from xlsx_output import write_estimate_xlsx
                    _fallback = write_estimate_xlsx(
                        summary, out_dir=OUTPUT_DIR / "estimates")
                    xlsx_path = str(_fallback)
                    print(f"   -> Fallback estimate xlsx: {_fallback.resolve()}")
                except Exception as _fb_exc:
                    print(f"   -> Fallback also failed: {_fb_exc}", flush=True)

        # ── Price read-back: stamp the REAL Excel-computed totals into the JSON ──
        # wb_populate writes Excel FORMULAS; the true unit cost is computed by Excel on load,
        # not in Python. The JSON's workbook_equivalent_pricing is a reconstruction that can
        # drift from the spreadsheet. Open the populated .xlsx via Excel COM, read the real
        # Material/Labour/Unit totals, and write them into the JSON so every consumer agrees.
        # Failure-isolated: any error leaves the JSON unchanged and never breaks the run.
        if xlsx_path:
            try:
                from wep_readback_from_xlsx import stamp_real_totals_into_json as _stamp_wep
                _canon_json = (summary.get("saved_output_paths") or {}).get("json")
                if _canon_json and Path(_canon_json).exists():
                    _stamp_wep(str(xlsx_path), str(_canon_json))
                else:
                    print("   [wep-readback] canonical JSON path not found — readback skipped.", flush=True)
            except Exception as _wep_exc:
                print(f"   [wep-readback] skipped ({_wep_exc}) — JSON unchanged, run continues.", flush=True)

        # THE READ-BACK STAMPS THE FILE ON DISK, NOT THIS SUMMARY.
        #
        # Everything after this point describes the job from the in-memory summary, and
        # without pulling the stamped blocks back into it the two provenance tabs are
        # written from a job that has no final_estimate at all. On 2085 that showed exactly
        # as you would expect: the Ext GBP column summed the engine's per-part figures to
        # GBP 44.75 against a Sell Price of GBP 6.33, with the money columns unlabelled and
        # no reconciliation line, because the code that writes both asks whether Excel has
        # calculated yet and the honest answer at that moment was no.
        if xlsx_path:
            try:
                _canon_json = (summary.get("saved_output_paths") or {}).get("json")
                if _canon_json and Path(_canon_json).exists():
                    with open(_canon_json, encoding="utf-8") as _fh_fe:
                        _stamped = json.load(_fh_fe)
                    if isinstance(_stamped.get("final_estimate"), dict):
                        summary["final_estimate"] = _stamped["final_estimate"]
                    _s_es = _stamped.get("estimate_summary")
                    if isinstance(_s_es, dict):
                        _m_es = summary.setdefault("estimate_summary", {})
                        for _k in ("workbook_equivalent_pricing", "cost_breakdown",
                                   "final_estimate"):
                            if isinstance(_s_es.get(_k), dict):
                                _m_es[_k] = _s_es[_k]
                    print(f"   [wep-readback] calculated totals merged into the run — the "
                          f"report sheets can now reconcile against them", flush=True)
            except Exception as _fe_exc:
                print(f"   [wep-readback] totals not merged ({_fe_exc}) — the report sheets "
                      f"will show engine figures and say so", flush=True)

        # SDI Intelligence — Decision Report + Provenance sheets
        # Added to whichever output was produced (wb_populate or fallback).
        #
        # AFTER the read-back, deliberately. These sheets state what Excel calculated and
        # reconcile the engine's per-part figures against it; written before the read-back
        # they had nothing to reconcile against and silently fell back to engine-only.
        if xlsx_path:
            try:
                import openpyxl as _opxl
                from job_decision_report import add_decision_report_sheet
                from estimation_report import add_provenance_sheet
                _wb = _opxl.load_workbook(str(xlsx_path))
                _scan_meta = {
                    "pdf_name":    str(scan_label),
                    "job_number":  str(scan_label).split("-")[0][:6],
                    "scan_date":   __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M"),
                }
                add_decision_report_sheet(_wb, summary, _scan_meta)
                add_provenance_sheet(_wb, summary, _scan_meta)
                _wb.save(str(xlsx_path))
                print(f"   -> Decision Report + AI Provenance sheets added")
            except Exception as _rep_exc:
                print(f"   -> Report sheets skipped: {_rep_exc}", flush=True)

        # ── Invariants: does this job hold together? ─────────────────────────────────
        # Everything above has finished writing. The workbook has calculated, the read-back
        # has stamped, and this is the last point at which the engine is looking at its own
        # output before anything describes it to a person. Every defect this engine has
        # shipped was visible here: rows that did not sum to their own total, costs joined to
        # the wrong parts, a quote naming an operation the sheet never charged. Nothing
        # compared them, so nothing objected.
        #
        # This never edits a price — silently correcting an unverified number is the failure
        # mode, not the fix. It marks the job, so a consumer can say "provisional" instead of
        # quoting a figure nobody stands behind.
        _canon_json3 = (summary.get("saved_output_paths") or {}).get("json")
        try:
            from invariants import check_job as _check_job, format_report as _fmt_inv
            # CHECK THE DOCUMENT THAT HAS EVERYTHING, ONCE.
            #
            # The read-back writes final_estimate to the JSON ON DISK, not to this in-memory
            # summary. Checking `summary` therefore ran six checks against a job with no
            # final_estimate at all, and they correctly reported themselves UNVERIFIED —
            # then the JSON was checked separately and found a third blocking violation the
            # console had never mentioned. One run, two verdicts: the console said 2 blocking
            # and 6 unverified while the quote said 3 failed.
            #
            # Fail-closed did its job — nothing claimed a pass it had not earned — but two
            # views of one job that disagree is the exact defect this layer exists to stop.
            # Load the stamped JSON first, check that, print that, store that.
            _doc = None
            if _canon_json3 and Path(_canon_json3).exists():
                try:
                    _doc = json.loads(Path(_canon_json3).read_text(encoding="utf-8"))
                except Exception as _rd:
                    print(f"   [invariants] could not read the stamped JSON ({_rd}) — "
                          f"checking the in-memory summary instead, which has no "
                          f"final_estimate and will report those checks as unverified.",
                          flush=True)
            _target = _doc if isinstance(_doc, dict) else summary
            _inv = _check_job(_target)
            summary["invariants"] = _inv          # so anything reading `summary` agrees
            print(_fmt_inv(_inv), flush=True)
            if not _inv.get("may_quote_firm"):
                # Said once, plainly, at the point a person is watching. The deliverables
                # below read the same record and mark themselves provisional; this is so the
                # console does not look like a clean run.
                print("   [invariants] THIS ESTIMATE IS NOT A FIRM PRICE — "
                      f"{_inv.get('blocking', 0)} check(s) failed, "
                      f"{_inv.get('unverified', 0)} could not be run. "
                      "Deliverables will be marked provisional; do not release to a customer "
                      "or an ERP export until resolved.", flush=True)
            if isinstance(_doc, dict) and _canon_json3:
                try:
                    Path(_canon_json3).write_text(
                        json.dumps(_doc, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as _iw:
                    print(f"   [invariants] could not stamp the JSON ({_iw}) — "
                          f"the console report above still stands.", flush=True)
        except Exception as _inv_exc:
            # A failed checker has verified NOTHING. Saying so is the point: a silent skip
            # here reads exactly like a clean pass.
            print(f"   [invariants] DID NOT RUN ({_inv_exc}) — this job is UNVERIFIED.",
                  flush=True)

        # ── Deliverables: client quote (always) + parity report (if a manual exists) ──
        # Opt-in via --deliverables. Each generator is failure-isolated: a report error logs and
        # the run continues — it never breaks the estimate. Manual lookup uses the UNC share root
        # (the K: mapping is session-dependent and fails) and skips gracefully when absent.
        if getattr(args, "deliverables", False) and xlsx_path:
            _canon_json2 = (summary.get("saved_output_paths") or {}).get("json")
            _out_dir = str(Path(str(xlsx_path)).parent)

            # Resolve the pinned manual estimate ONCE (explicit-only, no discovery) so
            # both the client quote (customer name from the ...\<CUSTOMER>\... path) and
            # the parity section below compare against the exact same spreadsheet. One job
            # folder can hold several manual .xls (cut&fold variant, revisions, outsource
            # copy), so we never guess — a wrong/absent path just means no parity, never a
            # silent fallback to a discovered file.
            _manual = None
            _explicit = getattr(args, "parity_workbook", None)
            if _explicit:
                _ep = Path(_explicit)
                if _ep.exists():
                    _manual = str(_ep)
                    print(f"   [deliverables] parity: using --parity-workbook {_manual}", flush=True)
                else:
                    print(f"   [deliverables] ERROR parity: --parity-workbook not found: {_ep}\n"
                          f"                  parity section SKIPPED — no auto-discovery. "
                          f"Fix the path and re-run.", flush=True)

            # 1) Client quote — always (needs only the summary JSON). The pinned manual
            #    workbook (when given) supplies the customer name from its folder path.
            if _canon_json2 and Path(_canon_json2).exists():
                try:
                    from client_quote_html import generate_quote_files as _gen_quote
                    _qpath = _gen_quote(str(_canon_json2), out_dir=_out_dir, job_stem=str(scan_label),
                                        manual_workbook=_manual, customer=getattr(args, "customer", None))
                    # None = deliberately suppressed by the credibility gate, which has
                    # already said why. Do not print a path that does not exist.
                    if _qpath:
                        print(f"   [deliverables] client quote -> {_qpath}", flush=True)
                except Exception as _q_exc:
                    print(f"   [deliverables] client quote skipped ({_q_exc}) — run continues.", flush=True)

                # 2) Unified job report — ALWAYS generated. The rich new-job report (7 sections:
                #    at-a-glance, what the engine got right, review items, drawing analysis,
                #    what to check, design recommendations, verdict). When a manual estimate is
                #    found (or pinned via --parity-workbook), a parity bundle is built and passed
                #    in, which ADDS the "1a Parity vs manual estimate" section. In production —
                #    a new enquiry with no manual — the SAME report renders without that section.
                #    (Replaces the old lean 5-section parity_report_html so parity and new-job
                #    runs share one report; parity_report_html remains available standalone.)
                try:
                    # Parity uses the SAME explicit-only manual workbook resolved above
                    # (_manual / _explicit). No auto-discovery here either.
                    _bundle_json = None
                    if _manual:
                        from estimate_full_parity_report import generate_and_write as _gen_bundle
                        _bundle_json = Path(_out_dir) / (re.sub(r"[^\w\- ]", "", str(scan_label)).strip() + "_parity_bundle.json")
                        _bundle_csv = _bundle_json.with_suffix(".csv")
                        # .xls reads via xlrd (computed values); an .xlsx manual may need Excel COM
                        # to resolve formulas — honour --full-parity-read-via-excel when set.
                        _gen_bundle(Path(_canon_json2), Path(_manual), _bundle_json, _bundle_csv,
                                    read_via_excel=bool(getattr(args, "full_parity_read_via_excel", False)))
                        print(f"   [deliverables] parity bundle built (manual: {_manual})", flush=True)
                    elif not _explicit:
                        print("   [deliverables] no --parity-workbook passed — new-job report only "
                              "(no parity section). Pass --parity-workbook <path> to compare against a "
                              "specific manual estimate.", flush=True)

                    from job_report_html import generate_report as _gen_job_report
                    _report_out = str(Path(_out_dir) / (re.sub(r"[^\w\- ]", "", str(scan_label)).strip() + "_report.html"))
                    _rhtml = _gen_job_report(
                        str(_canon_json2),
                        out_path=_report_out,
                        bundle_path=(str(_bundle_json) if _bundle_json else None),
                        job_stem=str(scan_label),
                    )
                    print(f"   [deliverables] job report -> {_rhtml}", flush=True)

                    # Retrievable LLM extract sidecar — the transcribed source data (BOM
                    # hierarchy, tube cut lengths, weights, material/finish, weld spec) written
                    # as a plain JSON next to the spreadsheet/quote/report so it can be OPENED
                    # and audited. This is what the estimate is built from; surfacing it proves
                    # what was captured vs what the costed output used. Written on every run.
                    _lfe = summary.get("llm_full_extract")
                    if isinstance(_lfe, dict) and (_lfe.get("bom") or _lfe.get("parts")):
                        _lfe_out = Path(_out_dir) / (re.sub(r"[^\w\- ]", "", str(scan_label)).strip()
                                                     + "_llm_extract.json")
                        with open(_lfe_out, "w", encoding="utf-8") as _fh_lfe:
                            json.dump(_lfe, _fh_lfe, indent=2, ensure_ascii=False)
                        _np = len(_lfe.get("parts") or [])
                        _nb = len(_lfe.get("bom") or [])
                        print(f"   [deliverables] LLM extract -> {_lfe_out} "
                              f"({_nb} BOM lines, {_np} parts) — open this to audit the source data",
                              flush=True)
                except Exception as _p_exc:
                    print(f"   [deliverables] job report skipped ({_p_exc}) — run continues.", flush=True)

        print("\nPage text preview:\n")
        for page in summary["pages"]:
            preview = (page["pdfplumber_text"] or "[NO TEXT EXTRACTED]").replace("\n", " ")
            print(f"Page {page['page_number']} ({page.get('page_role', {}).get('primary_role', 'unknown')}): {preview[:500]}\n")


if __name__ == "__main__":
    main()
