r"""
patch_deliverables_flag.py — add --deliverables orchestration to main.py.

When --deliverables is passed, AFTER the wep-readback (JSON has real totals):
  1. Client quote  -> ALWAYS (generate_quote_files on the canonical JSON, into the xlsx folder).
  2. Parity report -> ONLY if a manual estimate workbook is found for this job:
       locate via UNC convention <share>\<year>\<customer>\<jobfolder>\*.xls, build the bundle
       (generate_and_write), then the HTML (generate_report_files). Skip gracefully if no manual
       (the common 'new job' case) — never an error.
Both are FAILURE-ISOLATED: any exception logs and the run continues. Never breaks the estimate.

Two inserts:
  A) argparse: add --deliverables flag (after the existing flags, before parse_args return).
  B) orchestration block: after the wep-readback block (anchor: the readback's except line 725-726).

Uses in-scope vars: xlsx_path, summary (saved_output_paths.json), scan_label. Manual lookup uses
the UNC share root (K: mapping fails). Match-or-refuse, AST-validated, timestamped backup.
"""
import ast, re, shutil, datetime, os

T = r"C:\ClaudeVision\src\main.py"

# ---- Insert A: the --deliverables flag, right before 'return parser.parse_args()' ----
ANCHOR_A = "    return parser.parse_args()"
INSERT_A = '''    parser.add_argument(
        "--deliverables",
        action="store_true",
        help="After populate, generate client quote (always) + parity report (if a manual estimate is found).",
    )
    return parser.parse_args()'''

# ---- Insert B: orchestration, right after the readback except block ----
ANCHOR_B = '''            except Exception as _wep_exc:
                print(f"   [wep-readback] skipped ({_wep_exc}) — JSON unchanged, run continues.", flush=True)
'''
INSERT_B = ANCHOR_B + '''
        # ── Deliverables: client quote (always) + parity report (if a manual exists) ──
        # Opt-in via --deliverables. Each generator is failure-isolated: a report error logs and
        # the run continues — it never breaks the estimate. Manual lookup uses the UNC share root
        # (the K: mapping is session-dependent and fails) and skips gracefully when absent.
        if getattr(args, "deliverables", False) and xlsx_path:
            _canon_json2 = (summary.get("saved_output_paths") or {}).get("json")
            _out_dir = str(Path(str(xlsx_path)).parent)

            # 1) Client quote — always (needs only the summary JSON)
            if _canon_json2 and Path(_canon_json2).exists():
                try:
                    from client_quote_html import generate_quote_files as _gen_quote
                    _qpath = _gen_quote(str(_canon_json2), out_dir=_out_dir, job_stem=str(scan_label))
                    print(f"   [deliverables] client quote -> {_qpath}", flush=True)
                except Exception as _q_exc:
                    print(f"   [deliverables] client quote skipped ({_q_exc}) — run continues.", flush=True)

                # 2) Parity report — only if a manual estimate workbook is found
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
                    print(f"   [deliverables] parity report skipped ({_p_exc}) — run continues.", flush=True)
'''

# ---- The manual-lookup helper — insert once near the top of main() scope (after imports) ----
# Anchor: the 'args = parse_args()' line; put the helper def just above it at module level would be
# cleaner, but to keep it self-contained we define it as a module-level function before main runs.
# We anchor on the first line of parse_args() to insert the helper def just before it.
ANCHOR_H = "def parse_args() -> argparse.Namespace:"
INSERT_H = '''def _find_manual_workbook(scan_label: str, summary: dict):
    """Locate a manual estimate workbook for this job via the UNC share convention.
    <share>\\\\<year>\\\\<customer>\\\\<jobfolder>\\\\*.xls  — returns the first .xls found, else None.
    Uses the UNC root (the mapped K: drive is session-dependent and often absent). Never raises:
    any lookup problem returns None so the parity branch skips gracefully."""
    try:
        import glob, re as _re
        from pathlib import Path as _P
        share_root = r"\\\\sdi-dc01\\shareddata$\\Shared\\Estimating\\Completed\\Manual Estimates"
        if not os.path.isdir(share_root):
            return None
        job_num = str(scan_label).split("-")[0].strip()
        # year: prefer the job folder's mtime year via summary; fall back to scanning recent years
        candidates = []
        for year_dir in sorted(glob.glob(os.path.join(share_root, "20*")), reverse=True):
            # search customer/job folders whose name contains the job number
            for xls in glob.glob(os.path.join(year_dir, "*", "*" + job_num + "*", "*.xls")):
                candidates.append(xls)
            for xls in glob.glob(os.path.join(year_dir, "*" + job_num + "*", "*.xls")):
                candidates.append(xls)
        # de-dupe, prefer non-temp files
        seen = []
        for c in candidates:
            base = os.path.basename(c)
            if base.startswith("~$"):
                continue
            if c not in seen:
                seen.append(c)
        return seen[0] if seen else None
    except Exception:
        return None


def parse_args() -> argparse.Namespace:'''

def apply():
    src = open(T, encoding="utf-8").read()
    steps = [
        ("manual-lookup helper", ANCHOR_H, INSERT_H),
        ("--deliverables flag", ANCHOR_A, INSERT_A),
        ("orchestration block", ANCHOR_B, INSERT_B),
    ]
    for name, old, _ in steps:
        n = src.count(old)
        if n != 1:
            print(f"REFUSE at '{name}': anchor found {n} times (need 1). No changes written.")
            return False
    new = src
    for name, old, rep in steps:
        new = new.replace(old, rep, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: patched main.py fails AST parse: {e}. No changes written.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_deliverables_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: --deliverables wired (client quote always + parity if manual found, failure-isolated).")
    print(f"Backup: {os.path.basename(bak)}")
    print("Run with:  main.py --search-root <folder> --folder-as-job --deliverables")
    return True

if __name__ == "__main__":
    apply()
