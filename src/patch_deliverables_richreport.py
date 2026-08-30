r"""
patch_deliverables_richreport.py — swap the bare parity report for the unified rich report.

Replaces the --deliverables "report" branch so job_report_html.generate_report runs for EVERY job:
  - manual found  -> build the parity bundle, then generate_report(json, bundle_path=bundle)
                     => PARITY VARIANT (7 rich sections + §1a comparison)
  - no manual     -> generate_report(json)   => NEW-JOB VARIANT (7 rich sections, no comparison)

One report, one code path — fuller when a manual exists. Fully replaces parity_report_html (the rich
report supersedes it). The bundle build (generate_and_write) stays — it's the comparison data the
rich report reads. Client quote branch unchanged. Still failure-isolated.

Match-or-refuse on the exact current branch, AST-validated, timestamped backup.
"""
import ast, shutil, datetime, os

T = r"C:\ClaudeVision\src\main.py"

OLD = '''                # 2) Parity report — only if a manual estimate workbook is found
                try:
                    _manual = _find_manual_workbook(str(scan_label), summary)
                    if _manual:
                        from estimate_full_parity_report import generate_and_write as _gen_bundle
                        from parity_report_html import generate_report_files as _gen_parity_html
                        _bundle_json = Path(_out_dir) / (re.sub(r"[^\\w\\- ]", "", str(scan_label)).strip() + "_parity_bundle.json")
                        _bundle_csv = _bundle_json.with_suffix(".csv")
                        _gen_bundle(Path(_canon_json2), Path(_manual), _bundle_json, _bundle_csv, read_via_excel=False)
                        _phtml = _gen_parity_html(str(_bundle_json), out_dir=_out_dir, job_stem=str(scan_label))
                        print(f"   [deliverables] parity report -> {_phtml}", flush=True)
                    else:
                        print("   [deliverables] no manual estimate found — parity skipped (new job).", flush=True)
                except Exception as _p_exc:
                    print(f"   [deliverables] parity report skipped ({_p_exc}) — run continues.", flush=True)'''

NEW = '''                # 2) Rich job report — ALWAYS. Includes the parity comparison when a manual
                #    estimate is found (parity variant), or stands alone otherwise (new-job variant).
                try:
                    from job_report_html import generate_report as _gen_report
                    _bundle_for_report = None
                    _manual = _find_manual_workbook(str(scan_label), summary)
                    if _manual:
                        from estimate_full_parity_report import generate_and_write as _gen_bundle
                        _bundle_json = Path(_out_dir) / (re.sub(r"[^\\w\\- ]", "", str(scan_label)).strip() + "_parity_bundle.json")
                        _bundle_csv = _bundle_json.with_suffix(".csv")
                        _gen_bundle(Path(_canon_json2), Path(_manual), _bundle_json, _bundle_csv, read_via_excel=False)
                        _bundle_for_report = str(_bundle_json)
                        print(f"   [deliverables] manual found — parity variant (bundle built).", flush=True)
                    else:
                        print("   [deliverables] no manual — new-job variant (analysis only).", flush=True)
                    _rpath = _gen_report(str(_canon_json2), out_path=None,
                                         bundle_path=_bundle_for_report, job_stem=str(scan_label))
                    print(f"   [deliverables] report -> {_rpath}", flush=True)
                except Exception as _p_exc:
                    print(f"   [deliverables] report skipped ({_p_exc}) — run continues.", flush=True)'''

def apply():
    src = open(T, encoding="utf-8").read()
    n = src.count(OLD)
    if n != 1:
        print(f"REFUSE: report-branch anchor found {n} times (need 1). No changes.")
        return False
    new = src.replace(OLD, NEW, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: AST parse failed: {e}. No changes.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_richreport_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: --deliverables now emits the unified rich report (parity variant w/ manual, new-job variant without).")
    print(f"Backup: {os.path.basename(bak)}")
    print("job_report_html.py must be in src\\ (deploy it if not already).")
    return True

if __name__ == "__main__":
    apply()
