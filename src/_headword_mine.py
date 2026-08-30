# -*- coding: utf-8 -*-
"""Read-only: mine ONLY multi-word phrases anchored on a component HEAD-WORD from the 68k
historical lines. Proves the strict filter removes boilerplate and keeps real components.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_headword_mine.py"""
import config, re
from collections import Counter

# Physical purchased-component nouns. A bought-in phrase must END/CONTAIN one of these.
HEADWORDS = set("""
box clip strap cable light downlight loom screw bolt nut rivet nutsert insert washer
bracket magnet hinge castor glide tape tie grommet bush plug transformer driver lamp bulb
profile channel seal edging sticker label rail bar pin stud spacer foot bracketry connector
fixing fastener clamp gland sleeve cover cap knob handle catch latch lock plate
""".split())

STOP = set("""and the to of for with a an or per x mm cm m std part each set no not all from
as is by thru dia ext int down up rev semi gloss ral mat material description item misc inc
max min height width depth charge total cost delivery elc upc black white red blue grey green
clear natural left right top bottom front back qty quantity price unless otherwise stated""".split())

def toks(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return [w for w in s.split() if len(w) >= 2 and w not in STOP and not w.isdigit()]

conn = config.get_connection(); cur = conn.cursor()
cur.execute("SELECT line_description FROM dbo.historical_quote_material_line WHERE line_description IS NOT NULL")
descs = [r[0] for r in cur.fetchall()]
conn.close()
print(f"lines scanned: {len(descs):,}")

phrase = Counter()
for d in descs:
    ws = toks(str(d))
    # bigrams/trigrams that contain a head-word
    for n in (2, 3):
        for i in range(len(ws) - n + 1):
            gram = ws[i:i+n]
            if any(w in HEADWORDS for w in gram):
                phrase[" ".join(gram)] += 1

print("\n=== TOP 60 head-word-anchored component phrases (freq >= 5) ===")
for p, n in phrase.most_common(60):
    if n >= 5:
        print(f"  {n:6d}  {p}")
