r"""
READ-ONLY. Find the parity tooling and how it's invoked for 1282. We have several parity
scripts in the tree — identify the LIVE one, its CLI/entry point, and what benchmark it
compares the engine output against (Tim's manual estimate figures for 1282). No assumptions.
"""
import os, re, glob
root = r"C:\ClaudeVision\src"

# 1) list parity-related files with sizes/mtimes so we know which is live/current
print("="*70)
print("Parity-related scripts (name / size / mtime)")
print("="*70)
for p in sorted(glob.glob(os.path.join(root, "*parity*.py")) + glob.glob(os.path.join(root, "*parity*"))):
    try:
        st = os.stat(p)
        import datetime
        print(f"  {os.path.basename(p):<42} {st.st_size:>7}b  {datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}")
    except: pass

# 2) for each parity .py, show its top docstring + argparse/main so we know how to run it
print("\n"+"="*70)
print("Entry points / CLI for each parity script")
print("="*70)
for p in sorted(glob.glob(os.path.join(root, "*parity*.py"))):
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    print(f"\n---- {os.path.basename(p)} ----")
    # top docstring
    for ln in L[:8]:
        if ln.strip(): print(f"   {ln.rstrip()[:120]}")
    # argparse args + __main__
    for i,ln in enumerate(L):
        if re.search(r"add_argument|def main|__main__|benchmark|manual|1282|expected_total|target_total", ln):
            print(f"   {i+1}: {ln.strip()[:120]}")

# 3) where is the 1282 manual/benchmark figure stored? search for a benchmarks file/const
print("\n"+"="*70)
print("Where is the 1282 manual benchmark stored?")
print("="*70)
for p in glob.glob(os.path.join(root,"*.json")) + glob.glob(os.path.join(root,"*benchmark*")) + glob.glob(os.path.join(root,"*.py")):
    if os.path.getsize(p) > 500000: continue
    try: txt = open(p, encoding="utf-8", errors="replace").read()
    except: continue
    if re.search(r"1282", txt) and re.search(r"benchmark|manual_total|expected|target", txt, re.I):
        # show the lines
        for i,ln in enumerate(txt.splitlines()):
            if "1282" in ln and re.search(r"benchmark|manual|expected|target|\d{3}\.\d", ln, re.I):
                print(f"  {os.path.basename(p)}:{i+1}: {ln.strip()[:110]}")
