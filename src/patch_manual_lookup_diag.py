r"""
patch_manual_lookup_diag.py — make _find_manual_workbook say WHY it returns None.

The helper is correct and a standalone probe finds 1282's manual, yet the RUN printed 'no manual
found'. Rather than keep theorising, instrument the helper so the next run prints exactly which
check failed: share unreachable / job_num extracted / glob hit count / after-filter count. This
turns an uninformative skip into a precise diagnosis in ONE run.

Replaces the helper body with an instrumented version (same logic + [manual-lookup] prints). Also
makes the lookup MORE ROBUST: derive job_num from the job_folder in summary (stable) as well as
scan_label, and search both. Match-or-refuse on the exact current helper, AST-validated, backup.
"""
import ast, shutil, datetime, os

T = r"C:\ClaudeVision\src\main.py"

OLD = '''def _find_manual_workbook(scan_label: str, summary: dict):
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
        return None'''

NEW = '''def _find_manual_workbook(scan_label: str, summary: dict):
    """Locate a manual estimate workbook for this job via the UNC share convention.
    <share>\\\\<year>\\\\<customer>\\\\<jobfolder>\\\\*.xls  — returns the first .xls found, else None.
    Instrumented: prints [manual-lookup] diagnostics so a skip is explainable. Never raises."""
    try:
        import glob
        share_root = r"\\\\sdi-dc01\\shareddata$\\Shared\\Estimating\\Completed\\Manual Estimates"
        if not os.path.isdir(share_root):
            print(f"   [manual-lookup] share not reachable at run time: {share_root}", flush=True)
            return None
        # derive job number from BOTH scan_label and the job_folder in summary (more robust)
        cands_labels = [str(scan_label)]
        _jf = summary.get("job_folder") or summary.get("job_output_stem")
        if _jf:
            cands_labels.append(os.path.basename(str(_jf)))
        job_nums = []
        for lab in cands_labels:
            jn = str(lab).split("-")[0].strip()
            # keep only a leading numeric token (job numbers are numeric); strip any trailing words
            jn = jn.split()[0] if jn else jn
            if jn and jn not in job_nums:
                job_nums.append(jn)
        print(f"   [manual-lookup] scan_label={scan_label!r} job_nums={job_nums}", flush=True)
        candidates = []
        for year_dir in sorted(glob.glob(os.path.join(share_root, "20*")), reverse=True):
            for jn in job_nums:
                candidates += glob.glob(os.path.join(year_dir, "*", "*" + jn + "*", "*.xls"))
                candidates += glob.glob(os.path.join(year_dir, "*" + jn + "*", "*.xls"))
        print(f"   [manual-lookup] raw glob hits: {len(candidates)}", flush=True)
        seen = []
        for c in candidates:
            if os.path.basename(c).startswith("~$"):
                continue
            if c not in seen:
                seen.append(c)
        print(f"   [manual-lookup] after temp-filter: {len(seen)}"
              + (f" -> using {seen[0]}" if seen else " -> none"), flush=True)
        return seen[0] if seen else None
    except Exception as _mexc:
        print(f"   [manual-lookup] error ({type(_mexc).__name__}: {_mexc}) -> None", flush=True)
        return None'''

def apply():
    src = open(T, encoding="utf-8").read()
    n = src.count(OLD)
    if n != 1:
        print(f"REFUSE: helper anchor found {n} times (need 1). main.py differs — no changes.")
        return False
    new = src.replace(OLD, NEW, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: AST parse failed: {e}. No changes.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_manualdiag_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: _find_manual_workbook instrumented + made more robust. Backup: {os.path.basename(bak)}")
    print("Next --deliverables run prints [manual-lookup] lines showing exactly why it finds/skips.")
    return True

if __name__ == "__main__":
    apply()
