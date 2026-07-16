#!/usr/bin/env python3
"""
patch_dxf_reader_mfc.py  --  faced-board (MFC) recognition at the flat-pattern source.

Run from C:\\ClaudeVision\\src:   python patch_dxf_reader_mfc.py

The board parts read their material from dxf_reader's filename parser, which only knew
plain MDF. This teaches that parser the faced-board cue ("PRE LAM MDF", "MFMDF",
"MELAMINE FACED", "PRELAM", "MFC") so flat board parts resolve to MFC and route through
the sheet-yield price -- same regex already used as the MFC token in drawing_job_merge.py.

Idempotent: re-running is a no-op. Writes a .bak, preserves CRLF, compile-checks.
Aborts WITHOUT writing if an anchor is not found (your file differs from my reference)
-- in that case send the live dxf_reader.py and I will rebase.
"""
import json, sys, py_compile, shutil
from pathlib import Path

TARGET = Path("dxf_reader.py")
EDITS = json.loads(r'''[["_parse_material_from_stem", "    \"\"\"Extract material code from stem tokens (e.g. _MS_, _AL_).\"\"\"\r\n    for t in re.split(r'[_\\s]+', stem.upper()):", "    \"\"\"Extract material code from stem tokens (e.g. _MS_, _AL_).\"\"\"\r\n    if re.search(r\"MFMDF|MELAMINE\\s*FACED|PRE\\s*LAM(?:INATE)?|PRELAM|\\bMFC\\b\", stem.upper()):\r\n        return \"MFC\"\r\n    for t in re.split(r'[_\\s]+', stem.upper()):"], ["_parse_filename return", "    return {\r\n        \"part_number\":    part_number,\r\n        \"material\":       material,\r\n        \"thickness_mm\":   thickness_mm,", "    if re.search(r\"MFMDF|MELAMINE\\s*FACED|PRE\\s*LAM(?:INATE)?|PRELAM|\\bMFC\\b\", stem.upper()):\r\n        material = \"MFC\"\r\n    return {\r\n        \"part_number\":    part_number,\r\n        \"material\":       material,\r\n        \"thickness_mm\":   thickness_mm,"]]''')

def main():
    if not TARGET.exists():
        print(f"ABORT: {TARGET} not found. Run this from C:\\ClaudeVision\\src."); sys.exit(1)
    text = TARGET.read_bytes().decode("utf-8")

    if 'return "MFC"' in text and 'material = "MFC"' in text:
        print("Already patched (MFC recognition present) -- no change."); sys.exit(0)

    # verify every anchor first; write nothing unless all match
    for name, old, new in EDITS:
        if text.count(old) != 1:
            print(f"ABORT: anchor for [{name}] found {text.count(old)} times (expected 1).")
            print("Your dxf_reader.py differs from my reference. Send it and I'll rebase."); sys.exit(1)

    patched = text
    for name, old, new in EDITS:
        patched = patched.replace(old, new, 1)

    bak = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, bak)
    TARGET.write_bytes(patched.encode("utf-8"))

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TARGET)
        print(f"ABORT: patched file failed to compile, restored from .bak.\n{e}"); sys.exit(1)

    if 'return "MFC"' in patched and 'material = "MFC"' in patched:
        print("OK: dxf_reader.py patched for MFC (backup at dxf_reader.py.bak).")
        print("Verify:  python -c \"from dxf_reader import _parse_filename; from pathlib import Path; print(_parse_filename(Path('11087-17-02J_Shelf_PRE LAM MDF 19.6mm_RevJ.DXF'))['material'])\"")
    else:
        print("WARN: markers missing after patch -- check the file."); sys.exit(1)

if __name__ == "__main__":
    main()
