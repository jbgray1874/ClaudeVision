r"""
patch_manual_import_os.py — fix the NameError in _find_manual_workbook.

The helper uses os.path.isdir / os.path.join / os.path.basename but only imports glob inside the
function, relying on module-level `os`. In the function's execution scope `os` wasn't resolved ->
NameError -> swallowed by the bare except -> always returned None ('no manual found'). The
instrumentation revealed it.

FIX: add `import os` at the top of the function body (alongside the existing `import glob`).
One-line, contained. Match-or-refuse on the exact current 'import glob' line inside the helper,
AST-validated, backup.
"""
import ast, shutil, datetime, os

T = r"C:\ClaudeVision\src\main.py"

# The instrumented helper body starts with:  try:\n        import glob\n        share_root = ...
# Add `import os` right after `import glob` inside the helper. Anchor is unique to the helper.
OLD = '''    try:
        import glob
        share_root = r"\\\\sdi-dc01\\shareddata$\\Shared\\Estimating\\Completed\\Manual Estimates"'''
NEW = '''    try:
        import os, glob
        share_root = r"\\\\sdi-dc01\\shareddata$\\Shared\\Estimating\\Completed\\Manual Estimates"'''

def apply():
    src = open(T, encoding="utf-8").read()
    n = src.count(OLD)
    if n != 1:
        print(f"REFUSE: anchor found {n} times (need 1). No changes.")
        return False
    new = src.replace(OLD, NEW, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: AST parse failed: {e}. No changes.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_importos_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: added 'import os' inside _find_manual_workbook. Backup: {os.path.basename(bak)}")
    print("Re-run the direct-call test — it should now FIND the manual.")
    return True

if __name__ == "__main__":
    apply()
