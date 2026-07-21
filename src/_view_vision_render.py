r"""READ-ONLY. vision_extraction.py is the LIVE vision path at 144 DPI (Matrix 2,2). Show the render
code around line 130 so I patch it to 300 DPI using the good pattern from _bom_vision_reader
(zoom=dpi/72 + max_side cap), not a bare hardcode. Show the surrounding function + any existing
size/downscale handling so the patch fits. No edits."""
import re
p=r"C:\ClaudeVision\src\vision_extraction.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()

# show around the get_pixmap call
print("="*66); print("render context (110-150)"); print("="*66)
for i in range(109, min(len(L),150)):
    print(f"  {i+1}: {L[i].rstrip()[:100]}")

# is there any existing max_side / resize / downscale?
print("\n"+"="*66); print("existing size handling (resize / max_side / scale / downscale)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(max_side|resize|downscale|thumbnail|\.width|\.height|pix\.width|max_dim|MAX_)", ln):
        print(f"  {i+1}: {ln.strip()[:96]}")

# is DPI/zoom configurable or hardcoded? any config import?
print("\n"+"="*66); print("config knobs (is DPI configurable?)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(config|DPI|dpi|zoom|Matrix|getenv|VISION_)", ln):
        print(f"  {i+1}: {ln.strip()[:90]}")

# the enclosing function name
print("\n"+"="*66); print("enclosing function of the render"); print("="*66)
for i in range(129, -1, -1):
    if re.match(r"\s*def ", L[i]):
        print(f"  {i+1}: {L[i].strip()[:90]}")
        break
