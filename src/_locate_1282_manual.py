r"""READ-ONLY. The parity run couldn't find the manual .xls (K: expanded to a UNC path that
404'd). Locate the actual file: search both the K: mapping and the sdi-dc01 UNC root for the
1282 manual, print exact paths + whether each opens with xlrd. So we pass the real path. No edits."""
import os, glob
try:
    import xlrd
    have_xlrd=True
except Exception:
    have_xlrd=False

roots = [
    r"K:\Estimating\Completed\Manual Estimates\2026\TTI",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates\2026\TTI",
    r"K:\Estimating\Completed\Manual Estimates\2026",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates\2026",
]
print("Searching for the 1282 manual .xls ...\n")
found=[]
for root in roots:
    if not os.path.isdir(root):
        print(f"  [dir missing] {root}")
        continue
    print(f"  [dir OK]      {root}")
    # search recursively for anything with 1282 + .xls
    for p in glob.glob(os.path.join(root, "**", "*1282*"), recursive=True):
        if p.lower().endswith((".xls",".xlsx")):
            found.append(p)

print("\n--- 1282 workbook candidates ---")
seen=set()
for p in found:
    if p in seen: continue
    seen.add(p)
    ok="?"
    if have_xlrd and p.lower().endswith(".xls"):
        try:
            xlrd.open_workbook(p); ok="opens-OK"
        except Exception as e:
            ok=f"xlrd-fail:{type(e).__name__}"
    print(f"  {ok:<16} {p}")

if not seen:
    # widen: list the TTI folder contents so we see the exact folder/file names + spacing
    print("\n  No 1282 match — listing TTI folder tree so we see exact names:")
    for root in roots[:2]:
        if os.path.isdir(root):
            for dirpath, dirs, files in os.walk(root):
                depth=dirpath[len(root):].count(os.sep)
                if depth<=1:
                    for d in dirs:
                        if "1282" in d or "MILWAUKEE" in d.upper():
                            print(f"    DIR: {os.path.join(dirpath,d)}")
                    for f in files:
                        if "1282" in f or "MILWAUKEE" in f.upper():
                            print(f"    FILE: {os.path.join(dirpath,f)}")
