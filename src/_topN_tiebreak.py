r"""READ-ONLY. Several TOP 1 ... ORDER BY queries price bought-in parts. TOP 1 with a non-unique
ORDER BY returns an ARBITRARY tied row — which can vary between executions = the drift. Show each
TOP 1 query's FULL text (SELECT..ORDER BY) so I can see if the ORDER BY can leave TIES (e.g. two
rows same quote_date, or same price) with no unique final tiebreaker (a PK / id / sku).
This is the classic non-deterministic TOP-1 bug. No edits — find the tie-prone ones."""
import os, re
p=r"C:\ClaudeVision\src\pricing_service.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()

# find each 'SELECT TOP 1' / 'SELECT TOP' and print through its ORDER BY (or next ~30 lines)
starts=[i for i,ln in enumerate(L) if re.search(r"SELECT\s+TOP\s+1?\b", ln, re.I)]
for s in starts:
    print("\n"+"="*70)
    print(f"TOP-1 query starting line {s+1}")
    print("="*70)
    end=s
    for j in range(s, min(len(L), s+40)):
        end=j
        print(f"  {j+1}: {L[j].rstrip()[:100]}")
        if re.search(r"ORDER BY", L[j], re.I):
            # print 2 more lines to capture multi-line ORDER BY, then stop
            for k in range(j+1, min(len(L), j+4)):
                if re.search(r'"""|\'\'\'|\)\s*$|cursor|execute', L[k]): break
                print(f"  {k+1}: {L[k].rstrip()[:100]}")
            break

print("\n"+"="*70)
print("ASSESSMENT NOTES")
print("="*70)
print("  For each: does the ORDER BY end in a UNIQUE column (id/pk/sku/part_code)?")
print("  If it ends in DESC on a non-unique col (quote_date, price, cost) with NO unique")
print("  final tiebreaker, TWO tied rows -> arbitrary winner -> run-to-run drift.")
print("  The fix: append a unique final sort key (e.g. ', id DESC' or ', part_code ASC').")
