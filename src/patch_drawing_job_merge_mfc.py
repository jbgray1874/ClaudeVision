#!/usr/bin/env python3
r"""
patch_drawing_job_merge_mfc.py
------------------------------
The 4th file of the faced-board (MFC) lane, rebased to your live drawing_job_merge.py.
Adds an MFC / MFMDF / PRE-LAM token to _DXF_MATERIAL_TOKENS, immediately BEFORE the plain
\bMDF\b token, so a DXF filename like "PRE LAM MDF 19.6mm" resolves to the faced MFC class
(priced by the sheet) instead of plain MDF (priced by mass). This is the trigger the other
three files were waiting on.

Idempotent, anchored, writes .bak, preserves CRLF, compile-checks. Run from C:\ClaudeVision\src:
    python patch_drawing_job_merge_mfc.py
Then re-run main.py for the Trestle and parity-check it.
"""
import os, py_compile, json
JOBS = json.loads(r"""[["drawing_job_merge.py", "\"MFC\")", [["    (r\"\\bCARD\\b|GREYBOARD|GREY\\s*BOARD\", \"CARD\"),\n    (r\"\\bMDF\\b\", \"MDF\"),", "    (r\"\\bCARD\\b|GREYBOARD|GREY\\s*BOARD\", \"CARD\"),\n    # Faced board (melamine-faced / pre-lam MDF) - MUST precede plain MDF so it prices by sheet, not mass.\n    (r\"MFMDF|MELAMINE\\s*FACED|PRE\\s*LAM(?:INATE)?|PRELAM|\\bMFC\\b\", \"MFC\"),\n    (r\"\\bMDF\\b\", \"MDF\"),"]]]]""")
def patch_one(name, marker, pairs):
    path = os.path.abspath(name)
    if not os.path.isfile(path):
        print(f"[skip] {name}: not found at {path}"); return None
    with open(path, "r", encoding="utf-8", newline="") as f: raw = f.read()
    crlf = "\r\n" in raw; norm = raw.replace("\r\n", "\n")
    if marker in norm:
        print(f"[ok]   {name}: already applied (marker present) - no change"); return True
    for old, _new in pairs:
        n = norm.count(old)
        if n != 1:
            print(f"[ABORT] {name}: anchor matched {n}x (expected 1). Not written - send me the file and I'll rebase."); return False
    patched = norm
    for old, new in pairs: patched = patched.replace(old, new, 1)
    out = patched.replace("\n", "\r\n") if crlf else patched
    with open(path + ".bak", "w", encoding="utf-8", newline="") as f: f.write(raw)
    with open(path, "w", encoding="utf-8", newline="") as f: f.write(out)
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        with open(path, "w", encoding="utf-8", newline="") as f: f.write(raw)
        print(f"[FAIL] {name}: compile error - restored .bak\n{e}"); return False
    print(f"[done] {name}: patched, .bak written, compiles ({'CRLF' if crlf else 'LF'})"); return True
def main():
    print("Applying MFC token to drawing_job_merge.py ...\n")
    ok = all(patch_one(n,m,p) is not False for n,m,p in JOBS)
    print("\nDone." if ok else "\nAborted - nothing partial written.")
    if ok:
        print('Now: python main.py --search-root "...0354158_FlatPackTrestle" --folder-as-job')
    return 0 if ok else 1
if __name__ == "__main__": raise SystemExit(main())
