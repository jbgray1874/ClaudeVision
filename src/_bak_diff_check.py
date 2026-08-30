r"""
READ-ONLY. The .bak_shapely is 9 hours stale. Before trusting/discarding it, see what differs
between live dxf_reader.py.py and the stale backup. If the ONLY differences are the shapely
net-area block (the helper + the shoelace->shapely swap + signature), the backup is safe to
use for reverting shapely. If there are OTHER differences, the backup is dangerous (would lose
9h of edits) and we must NOT restore it — instead fix powder in wb_populate.py without touching
dxf_reader.
"""
import difflib, os
live = r"C:\ClaudeVision\src\dxf_reader.py.py"
bak  = r"C:\ClaudeVision\src\dxf_reader.py.py.bak_shapely"
a = open(bak, encoding="utf-8", errors="replace").read().splitlines()
b = open(live, encoding="utf-8", errors="replace").read().splitlines()
print(f"stale backup: {len(a)} lines, {os.path.getsize(bak)} bytes")
print(f"live file:    {len(b)} lines, {os.path.getsize(live)} bytes\n")

sm = difflib.SequenceMatcher(None, a, b)
print("=== change blocks (backup -> live) ===")
shapely_markers = ("_shapely_net_area", "polygonize", "unary_union", "area_method", "cut_circs", "shapely")
n_blocks = 0
n_shapely = 0
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal": continue
    n_blocks += 1
    block_txt = " ".join(b[j1:j2] + a[i1:i2]).lower()
    is_shapely = any(m in block_txt for m in shapely_markers)
    if is_shapely: n_shapely += 1
    label = "  [shapely]" if is_shapely else "  [!!! NON-SHAPELY EDIT !!!]"
    print(f"{label} {tag} backup[{i1+1}:{i2}] -> live[{j1+1}:{j2}]")
    # show a couple lines
    for ln in (b[j1:j2][:3] if tag!="delete" else a[i1:i2][:3]):
        print(f"       {ln.strip()[:110]}")
print(f"\n{n_blocks} change blocks; {n_shapely} look shapely-related, {n_blocks-n_shapely} do NOT")
if n_blocks == n_shapely:
    print("=> ALL differences are shapely. The stale backup IS safe to revert shapely (nothing else lost).")
else:
    print("=> There are NON-shapely differences. DO NOT restore the backup — it would lose other edits.")
    print("   Instead: leave shapely applied, fix powder in wb_populate.py (inclusion test).")
