r"""READ-ONLY. The previous confirm script hardcoded max_side=4000 via setdefault, so it never saw
the .env value. This one loads C:\ClaudeVision\.env exactly like the pipeline does, reads the REAL
VISION_MAX_SIDE + VISION_RENDER_DPI, and renders A3 with those to show the true effective DPI.
No edits."""
import os

# load .env the way main.py does (python-dotenv if present, else manual parse)
env_path=r"C:\ClaudeVision\.env"
loaded=False
try:
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    loaded="python-dotenv"
except ImportError:
    # manual parse
    if os.path.exists(env_path):
        for line in open(env_path,encoding="utf-8",errors="replace"):
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1)
                os.environ[k.strip()]=v.strip().strip('"').strip("'")
        loaded="manual-parse"

print("="*60)
print(f".env loaded via: {loaded}")
print(f"  VISION_RENDER_DPI = {os.getenv('VISION_RENDER_DPI', '(not set -> default 300)')}")
print(f"  VISION_MAX_SIDE   = {os.getenv('VISION_MAX_SIDE', '(not set -> default 4000)')}")
print("="*60)

# render A3 with the REAL env values
vis_dpi=float(os.getenv("VISION_RENDER_DPI","300"))
vis_max=float(os.getenv("VISION_MAX_SIDE","4000"))
try:
    import fitz
except ImportError:
    print("fitz not available"); raise SystemExit

pdf=r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay\1455-C-GA 500mm Milwaukee Header_revC.PDF"
if not os.path.exists(pdf):
    print(f"PDF not reachable: {pdf}"); raise SystemExit

doc=fitz.open(pdf); page=doc.load_page(0); rect=page.rect
long_pts=max(float(rect.width),float(rect.height))
zoom=vis_dpi/72.0
capped=False
if long_pts*zoom>vis_max and long_pts>0:
    zoom=vis_max/long_pts; capped=True
pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False)
eff=zoom*72
print(f"A3 page {rect.width:.0f}x{rect.height:.0f}pt -> {pix.width}x{pix.height}px")
print(f"effective DPI: {eff:.0f}   {'(CAPPED by max_side=%.0f)'%vis_max if capped else '(uncapped — true target)'}")
print()
if eff>=299:
    print("  ✓ RESOLVED — true 300 DPI on A3. Your .env VISION_MAX_SIDE is working.")
elif eff>242:
    print(f"  Partial — {eff:.0f} DPI. If <300, raise VISION_MAX_SIDE further (A3 needs ~4960).")
else:
    print(f"  Still {eff:.0f} — .env value not picked up. VISION_MAX_SIDE in env = {os.getenv('VISION_MAX_SIDE')}")
doc.close()
