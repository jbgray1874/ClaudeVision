# -*- coding: utf-8 -*-
"""Read-only: mine recurring COMPONENT TYPE-WORDS from historical material lines.
This becomes the seed for the layer-2 deterministic prose recogniser. We extract words/
bigrams that recur across bought-in descriptions, drop stopwords/numbers/codes, rank by
frequency. The point: SHOW what mining gives so it's concrete, not theoretical.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_typevocab_mine.py"""
import config, re
from collections import Counter

conn = config.get_connection(); cur = conn.cursor()

# Pull bought-in-ish descriptions: material lines + the curated bought_in_parts.
descs = []
try:
    cur.execute("SELECT line_description FROM dbo.historical_quote_material_line WHERE line_description IS NOT NULL")
    descs += [r[0] for r in cur.fetchall()]
except Exception as e:
    print("material_line read err:", e)
try:
    cur.execute("SELECT description FROM dbo.bought_in_parts WHERE description IS NOT NULL")
    descs += [r[0] for r in cur.fetchall()]
except Exception as e:
    print("bought_in_parts read err:", e)
print(f"descriptions pulled: {len(descs):,}\n")

STOP = set("""and the to of for with a an or be in on per x mm cm m std part each set kg
no not all from as is by off thru dia ext int down up rev semi gloss ral mat material
black white red blue grey green clear natural left right top bottom front back""".split())

def words(s):
    s = s.lower()
    s = re.sub(r"[^a-z ]", " ", s)        # drop digits, codes, punctuation
    return [w for w in s.split() if len(w) >= 3 and w not in STOP]

uni = Counter(); bi = Counter()
for d in descs:
    ws = words(str(d))
    uni.update(ws)
    bi.update(" ".join(p) for p in zip(ws, ws[1:]))

print("=== TOP 50 single type-words (frequency) ===")
for w, n in uni.most_common(50):
    print(f"  {n:6d}  {w}")
print("\n=== TOP 40 two-word type phrases (frequency) ===")
for w, n in bi.most_common(40):
    print(f"  {n:6d}  {w}")

conn.close()
