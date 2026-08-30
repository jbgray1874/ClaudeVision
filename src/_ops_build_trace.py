r"""
READ-ONLY. Find where a part's OPERATION LIST (textual_operations / operations) is
finalized before it becomes labour — so a general 'add folding when fold evidence exists'
fix lands where it actually reaches the Fold labour row (not just a field).

Prints the relevant regions of estimator.py and json_normaliser.py, and shows how the
Fold labour row is generated (what field it reads to decide 'this part folds').
"""
import os, re
root = r"C:\ClaudeVision\src"

def show(fn, patterns, ctx=2):
    p = os.path.join(root, fn)
    if not os.path.exists(p):
        print(f"  ({fn} not found)"); return
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    printed=set()
    for i, ln in enumerate(L):
        if any(re.search(pat, ln) for pat in patterns):
            lo,hi=max(0,i-ctx),min(len(L),i+ctx+1)
            for j in range(lo,hi):
                if j not in printed:
                    print(f"  {j+1}: {L[j].rstrip()[:150]}")
                    printed.add(j)
            print("  ---")

print("="*70)
print("estimator.py — textual_operations build + where 'folding'/bends -> operation")
print("="*70)
show("estimator.py", [r'textual_operations', r'inferred_operations', r'"folding"',
                      r'\bfolding\b', r'operations\s*=', r'bends\b.*operation', r'add.*fold'], ctx=3)

print("\n"+"="*70)
print("Where does the FOLD LABOUR ROW get created? (what decides a part folds)")
print("="*70)
# the labour grouping reads operations -> normaliser -> WB op. find the op->labour bridge.
show("estimator.py", [r'op_name_map|OP_NAME_MAP|normalise_operation|operation_normaliser',
                      r'for op in.*operations', r'FOLD|Folding'], ctx=2)

print("\n"+"="*70)
print("json_normaliser.py — combined_ops (operation list assembly)")
print("="*70)
show("json_normaliser.py", [r'textual_operations', r'combined_ops', r'folding', r'FOLD'], ctx=3)

print("\n"+"="*70)
print("KEY QUESTION: what field does the labour builder read to emit a Fold op?")
print("  If it reads textual_operations containing 'folding' -> fix = add 'folding' when")
print("  fold evidence (angles_deg/fold_count_textual/bend_count>0) and NOT tube/bar.")
print("="*70)
