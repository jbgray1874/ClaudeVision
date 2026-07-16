"""READ-ONLY. For the 4 questionable electrical prices (junction box £1.04, mains cable
£0.42, earth strap £1.04, downlights £26.00), show EXACTLY which historical line each
matched and how strong the match is - so we can judge keep / re-match / flag-unpriced.

It replays the real recogniser matching against the live DB (loads self.priced from
dbo.historical_quote_material_line), and for each phrase shows: the best Jaccard match
(the general matcher, which is what actually fired for these), the score, and the shared
tokens. A low score / weird shared token = coincidental match = should be flagged £0.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _verify_electrical_prices.py
"""
import sys
sys.path.insert(0, r"C:\ClaudeVision\src")
import config
import bought_in_recogniser as m

ref = m.get_reference(config.get_connection)
print(f"Loaded {len(ref.priced)} priced historical lines.\n")

def _sig(s):
    return m._sig_token_set(s)

# The 4 questionable items, as the recogniser sees them (phrase.title()'d desc)
PHRASES = ["Junction Box", "Mains Cable", "Earth Strap", "Led Downlights"]

for phrase in PHRASES:
    print("=" * 72)
    print(f"PHRASE: '{phrase}'   tokens={sorted(_sig(phrase))}")
    print("=" * 72)

    # 1. What the GENERAL Jaccard matcher returns (this is what fired -> the £ we saw)
    gm = ref.best_priced_match(phrase)
    if gm:
        shared = sorted(_sig(phrase) & _sig(gm["matched_desc"]))
        print(f"  [general Jaccard match]  £{gm['price']:.2f}  score={gm['match_score']}")
        print(f"     matched line : '{gm['matched_desc']}'")
        print(f"     shared tokens: {shared}")
        verdict = "STRONG" if gm["match_score"] >= 0.6 else ("WEAK - likely coincidental" if gm["match_score"] < 0.4 else "borderline")
        print(f"     -> {verdict}")
    else:
        print("  [general Jaccard match]  none (would flag unpriced)")

    # 2. What the ELECTRICAL anchor matcher would return (band-guarded, specificity-ranked)
    key = m._norm(phrase)
    em = ref.electrical_priced_match(key)
    if em:
        print(f"  [electrical anchor match] £{em['price']:.2f}  score={em['match_score']}  <- '{em['matched_desc']}'")
    else:
        anchors = m._ELECTRICAL_ANCHORS.get(key)
        print(f"  [electrical anchor match] none  (anchors={anchors} not found in-band -> would flag unpriced)")

    # 3. Show the top 3 in-band candidates by shared-token count, for eyeballing
    ptoks = _sig(phrase)
    scored = []
    for r in ref.priced:
        sh = len(ptoks & r["desc_tokens"])
        if sh >= 1:
            scored.append((sh, r["price"], r["desc"]))
    scored.sort(key=lambda t: (-t[0], t[1]))
    print("  nearest priced lines (by shared tokens):")
    for sh, price, desc in scored[:3]:
        print(f"     shared={sh}  £{price:.2f}  '{desc[:70]}'")
    print()

print("GUIDE: score >=0.6 strong; 0.4-0.6 borderline; <0.4 coincidental (should flag £0).")
print("If a match's shared tokens are generic (e.g. only 'box' or 'cable'), it is not a real")
print("same-part match -> better to flag unpriced (estimator to price) than apply a wrong £.")
