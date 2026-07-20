r"""
Patch: insert the flagged dual-path BOM override into file_scan._finalize_scan_summary,
between 'done merge_page_analysis' and 'start build_document_writeup' -- i.e. exactly
where document_analysis['bom_rows'] can be replaced before build_document_writeup
consumes it. _finalize_scan_summary is the single common finalizer for all three scan
modes (folder-job / DXF / single-PDF), and already has pdf_path, job_folder, and
summary['full_path'] in scope, so ONE insertion covers every job.

Behaviour:
  - env SDI_DUALPATH_BOM unset  -> hook is inert; bom_rows untouched (baseline exact).
  - env SDI_DUALPATH_BOM=1|true|yes -> dual-path reconciled rows replace bom_rows.
  - any exception inside the hook -> existing rows kept (a scan never breaks on this).

Exact-string match-or-refuse; also ensures 'import os' is present.

Run:
  C:\ClaudeVision\.venv\Scripts\python.exe patch_file_scan_dualpath_hook.py
"""
import pathlib

SRC = pathlib.Path(r"C:\ClaudeVision\src\file_scan.py")

ANCHOR = (
    '    summary = merge_page_analysis(summary, geom_pages)\n'
    '    _debug("done merge_page_analysis")\n'
    '    _debug("start build_document_writeup")\n'
)

HOOK = (
    '    summary = merge_page_analysis(summary, geom_pages)\n'
    '    _debug("done merge_page_analysis")\n'
    '\n'
    '    # -- Dual-path BOM override (flagged, default OFF) --------------------------\n'
    '    # When SDI_DUALPATH_BOM is set, the deterministic (pdfplumber) + vision (Grok)\n'
    '    # reconciled reader becomes the authoritative source of the bom_rows that\n'
    '    # build_document_writeup consumes below. Flag OFF => byte-identical to baseline.\n'
    '    # Any failure leaves the existing rows untouched (a scan never breaks on this).\n'
    '    if os.getenv("SDI_DUALPATH_BOM", "").lower() in {"1", "true", "yes"}:\n'
    '        try:\n'
    '            from bom_pipeline import reconciled_bom_rows_for_job\n'
    '            if job_folder and summary.get("scan_mode") == "folder_as_job":\n'
    '                _dp = reconciled_bom_rows_for_job(folder=job_folder)\n'
    '            elif pdf_path:\n'
    '                _dp = reconciled_bom_rows_for_job(pdfs=[pdf_path])\n'
    '            else:\n'
    '                _fp_src = summary.get("full_path") or summary.get("source_file")\n'
    '                _dp = reconciled_bom_rows_for_job(pdfs=[_fp_src]) if _fp_src else {"rows": []}\n'
    '            if _dp.get("rows"):\n'
    '                _da = summary.setdefault("document_analysis", {})\n'
    '                _da["bom_rows"] = _dp["rows"]\n'
    '                _da["bom_code_quality_findings"] = _dp.get("findings", [])\n'
    '                _debug(f"dual-path bom_rows applied: {len(_dp[\'rows\'])} rows")\n'
    '        except Exception as _dp_err:\n'
    '            _debug(f"dual-path bom_rows hook skipped: {_dp_err}")\n'
    '\n'
    '    _debug("start build_document_writeup")\n'
)


def run():
    src = SRC.read_text(encoding="utf-8")
    if "SDI_DUALPATH_BOM" in src:
        print("ABORT: dual-path hook already present -- nothing changed.")
        return
    if src.count(ANCHOR) != 1:
        print(f"ABORT: anchor found {src.count(ANCHOR)} times (need exactly 1). "
              "Nothing changed. Paste the current _finalize_scan_summary head so I can re-key.")
        return
    src2 = src.replace(ANCHOR, HOOK, 1)

    # ensure 'import os' is available
    if "\nimport os\n" not in src2 and not src2.startswith("import os\n"):
        # insert after the first line that starts an import block
        lines = src2.splitlines(keepends=True)
        for k, ln in enumerate(lines):
            if ln.startswith(("import ", "from ")):
                lines.insert(k, "import os\n")
                break
        src2 = "".join(lines)
        print("note: added 'import os' (was not present).")

    import ast
    try:
        ast.parse(src2)
    except SyntaxError as e:
        print(f"ABORT: patched result failed syntax check ({e}). Nothing written.")
        return
    SRC.write_text(src2, encoding="utf-8")
    print("OK: dual-path BOM hook inserted in _finalize_scan_summary (default OFF).")
    print()
    print("RUN 1282 BOTH WAYS (the change-detector diff):")
    print(r'  # baseline (flag off) -- expect ~278.76, money_fail 0')
    print(r'  Remove-Item Env:\SDI_DUALPATH_BOM -ErrorAction SilentlyContinue')
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe main.py --search-root "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job')
    print(r'  # dual-path (flag on) -- read the delta, decompose every penny')
    print(r'  $env:SDI_DUALPATH_BOM="1"')
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe main.py --search-root "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job')


if __name__ == "__main__":
    run()
