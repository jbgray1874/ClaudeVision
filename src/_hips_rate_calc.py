"""READ-ONLY. Derive a real £/m2 rate per thickness for HIPS from full-size UDEF stock
sheets, so we can set a defensible per-thickness board rate (Approach B). Parses the
'LxWxTmm' dimensions out of the description and divides System cost per by sheet area.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _hips_rate_calc.py"""
import pyodbc, config, re
from collections import defaultdict

c = config.PRICE_SOURCE_CONFIG["udef_sqlserver"]
conn = pyodbc.connect(
    f"DRIVER={{{c['driver']}}};SERVER={c['server']};DATABASE={c['database']};"
    f"UID={c['username']};PWD={c['password']};Encrypt=yes;TrustServerCertificate=yes;",
    timeout=30)
cur = conn.cursor()
cur.execute(
    "SELECT [Part code],[Description],[System cost per] "
    "FROM UDEF_PARTS_TABLE_FOR_ESTIMATING "
    "WHERE [Description] LIKE '%HIPS%' AND [System cost per] > 0")
rows = cur.fetchall()
conn.close()

# Parse "L x W x Tmm" — pull three numbers where the 3rd is small (thickness)
pat = re.compile(r"(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d(?:\.\d+)?)\s*mm", re.I)
by_thk = defaultdict(list)
print(f"{'Part':<16} {'L':>7} {'W':>7} {'T':>5} {'m2':>7} {'£':>8} {'£/m2':>8}")
print("-" * 62)
for code, desc, cost in rows:
    m = pat.search(desc or "")
    if not m:
        continue
    L, W, T = float(m.group(1)), float(m.group(2)), float(m.group(3))
    area = (L * W) / 1_000_000.0
    if area < 0.05:          # skip tiny offcuts — not representative stock
        continue
    cost = float(cost)
    if cost <= 0:
        continue
    rate = cost / area
    if rate > 100:           # skip printed/flocked/mirrored premium items
        continue
    by_thk[T].append(rate)
    print(f"{code:<16} {L:>7.0f} {W:>7.0f} {T:>5.1f} {area:>7.3f} {cost:>8.2f} {rate:>8.2f}")

print("\n" + "=" * 40)
print("MEDIAN £/m2 per thickness (plain HIPS stock)")
print("=" * 40)
import statistics
for t in sorted(by_thk):
    vals = sorted(by_thk[t])
    med = statistics.median(vals)
    print(f"  {t:>4.1f}mm : £{med:6.2f}/m2   (n={len(vals)}, range £{vals[0]:.2f}-£{vals[-1]:.2f})")
