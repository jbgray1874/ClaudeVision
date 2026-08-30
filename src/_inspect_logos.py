r"""READ-ONLY. Inspect the customer-logo files JG dropped in assets\customer_logos so we can
normalise naming + confirm the HTML ones are bare <svg> logos (not full quote pages). Show each
file: size, and for HTML/SVG a peek at whether it starts with <svg (good, a logo) or <!DOCTYPE/
<html (a full page — needs the <svg> extracted). No edits."""
import os, re
d=r"C:\ClaudeVision\assets\customer_logos"
if not os.path.isdir(d):
    print("FOLDER NOT FOUND:", d); raise SystemExit
for fn in sorted(os.listdir(d)):
    p=os.path.join(d,fn)
    if not os.path.isfile(p): continue
    sz=os.path.getsize(p)
    ext=os.path.splitext(fn)[1].lower()
    kind=""
    if ext in (".html",".svg",".htm"):
        head=open(p,encoding="utf-8",errors="replace").read(400).lstrip().lower()
        if head.startswith("<svg"):
            kind="BARE <svg> (good — usable as a logo)"
        elif "<svg" in head:
            kind="has <svg> but not at top (extractable)"
        elif head.startswith(("<!doctype","<html")):
            # is there an svg anywhere?
            full=open(p,encoding="utf-8",errors="replace").read()
            n=full.lower().count("<svg")
            kind=f"FULL HTML PAGE ({'contains '+str(n)+' <svg>' if n else 'no <svg> — probably a full quote page, NOT a logo'})"
        else:
            kind="unknown text"
    elif ext==".png":
        kind="PNG (embed as base64 — fine)"
    print(f"  {fn:<22} {sz:>8} bytes  {kind}")
