import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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
            summary, output_paths = scan_folder_job(
                job_folder,
                job_files,
                attach_dxf_paths=None,
                auto_discover_dxf=auto_discover_dxf,
            )
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
        try:
            from xlsx_output import write_estimate_xlsx
            xlsx_path = write_estimate_xlsx(summary, out_dir=OUTPUT_DIR / "estimates")
            print(f"\nEstimate xlsx: {xlsx_path.resolve()}")

            # SDI Intelligence — Decision Report + Provenance sheets
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

        except Exception as exc:
            print(f"\nEstimate xlsx skipped: {exc}", flush=True)

        print("\nPage text preview:\n")
        for page in summary["pages"]:
            preview = (page["pdfplumber_text"] or "[NO TEXT EXTRACTED]").replace("\n", " ")
            print(f"Page {page['page_number']} ({page.get('page_role', {}).get('primary_role', 'unknown')}): {preview[:500]}\n")


if __name__ == "__main__":
    main()
