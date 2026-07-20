"""Copy Downloads v3 pretty report into src."""
import shutil
from pathlib import Path

src = Path(r"c:\Users\james.gray\Documents\Downloads\estimate_parity_pretty_report (3).py")
dst = Path(__file__).resolve().parent / "estimate_parity_pretty_report.py"
shutil.copy2(src, dst)
import py_compile
py_compile.compile(str(dst), doraise=True)
print("copied", dst, "bytes", dst.stat().st_size)
