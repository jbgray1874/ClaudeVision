"""Adds Live Orders to a running SDI Intelligence portal. Written 20 Nov 2026.

    python add_live_orders_to_portal.py                        # PREVIEW: shows what it would change, changes nothing
    python add_live_orders_to_portal.py --apply                # makes the changes (backs up first)
    python add_live_orders_to_portal.py --target <backend folder> --runs <SDI_X3_runs folder>

Default target: C:\\ClaudeVision\\sdi-intelligence-backend (the folder the SDIIntelligence service runs). It only ADDS:
  1. live_orders_routes.py and live_orders_dashboard.html, copied next to app.py
  2. two lines in app.py that mount the Live Orders endpoints (beside the HR ones)
  3. a "Live Orders" menu item, its page (the dashboard in a frame) and its label in sdi-intelligence-portal.html
  4. the Live Orders settings in .env (only those missing; a LIVE_ORDERS_ROUTES whose file isn't there is commented
     out, so the routings come from Sage X3): runs folder, Production's folder (network path), the
     repo's live_orders folder, the route file, the X3 API settings file and exports folder - full paths, because
     the service runs as a system account (no mapped drives, no home folder of yours)
Every changed file is backed up first as <name>.bak-<date time>. Safe to run twice: anything already there is skipped.
Nothing else is touched. Restart the SDIIntelligence service afterwards so app.py is re-read.
"""
import argparse
import re
import datetime as dt
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DASH = REPO / "sagex3" / "production" / "live_orders" / "live_orders_dashboard.html"

MOUNT = ('# -- Live Orders (Sage X3 -> board -> dashboard), read-only --\n'
         'from live_orders_routes import router as live_orders_router\n'
         'app.include_router(live_orders_router)\n')
NAV = ('      <a data-view="liveorders"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
       'stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="9" x2="17" y2="9"/>'
       '<line x1="7" y1="13" x2="13" y2="13"/><line x1="7" y1="17" x2="15" y2="17"/></svg>Live Orders</a>\n')
SECTION = ('    <section class="view" id="liveorders">\n'
           '      <iframe id="lo-frame" title="Live Orders" style="width:100%;height:calc(100vh - 150px);border:0;'
           'border-radius:10px;background:#fff"></iframe>\n'
           '    </section>\n')
FRAME_JS = ('  // Live Orders: the dashboard reads /api/live-orders/latest with the portal key (after #, never sent to the server)\n'
            '  (function(){const f=document.getElementById("lo-frame");'
            'if(f)f.src="/api/live-orders/dashboard#key="+encodeURIComponent(API_KEY||"");})();\n')


def plan(target, runs, opts):
    app, page, env = target / "app.py", target / "sdi-intelligence-portal.html", target / ".env"
    for f in (app, page):
        if not f.exists():
            sys.exit(f"Not found: {f} - is --target the folder with app.py and the portal page?")
    changes = []                                    # (file, new text or None for a copy, source, description)
    for src, name in ((HERE / "live_orders_routes.py", "live_orders_routes.py"), (DASH, "live_orders_dashboard.html")):
        dst = target / name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            changes.append((dst, None, src, f"copy {name}" + (" (update)" if dst.exists() else "")))

    a = app.read_text(encoding="utf-8")
    if "live_orders_routes" not in a:
        anchor = "app.include_router(hr_router)\n"
        if anchor in a:
            a2 = a.replace(anchor, anchor + "\n" + MOUNT, 1)
        else:
            i = a.find('if __name__ == "__main__":')
            if i < 0:
                sys.exit("app.py: could not find where to add the two lines - add them by hand:\n" + MOUNT)
            a2 = a[:i] + MOUNT + "\n\n" + a[i:]
        changes.append((app, a2, None, "app.py: mount the Live Orders endpoints"))

    p = page.read_text(encoding="utf-8")
    p2 = p
    if 'data-view="liveorders"' not in p2:
        anchor = '<div class="grp">AI Services</div>'
        if anchor not in p2:
            sys.exit("portal page: could not find the menu - not changed")
        p2 = p2.replace(anchor, NAV.strip() + "\n      " + anchor, 1)
    if 'id="liveorders"' not in p2:
        anchor = '    <section class="view" id="aisvc">'
        if anchor not in p2:
            sys.exit("portal page: could not find where pages start - not changed")
        p2 = p2.replace(anchor, SECTION + anchor, 1)
    if "liveorders:'Live Orders'" not in p2:
        p2 = p2.replace("const labels={dashboard:'Dashboard',", "const labels={dashboard:'Dashboard',liveorders:'Live Orders',", 1)
    if 'id("lo-frame")' not in p2 and "getElementById(\"lo-frame\")" not in p2:
        anchor = "  function _hdr(){"
        if anchor not in p2:
            sys.exit("portal page: could not find the API key script - not changed")
        p2 = p2.replace(anchor, FRAME_JS + anchor, 1)
    if p2 != p:
        changes.append((page, p2, None, "portal page: Live Orders menu item, page and label"))

    e = env.read_text(encoding="utf-8") if env.exists() else ""
    want = {"LIVE_ORDERS_RUNS": runs, "LIVE_ORDERS_SHARE": opts.share, "LIVE_ORDERS_SHARE_USER": opts.share_user,
            "LIVE_ORDERS_HOME": str(REPO / "sagex3" / "production" / "live_orders"), "LIVE_ORDERS_ROUTES": opts.routes_file,
            "X3_API_CONFIG": opts.x3_config, "X3_EXPORT_DIR": opts.exports,
            "LIVE_ORDERS_PYTHON": sys.executable}          # the python you run this with (it has openpyxl)
    bad = [m for m in re.finditer(r"(?m)^LIVE_ORDERS_ROUTES=(.*)$", e)   # a route file that isn't there (e.g. a
           if not Path(m.group(1).strip().strip('"')).is_file()]            # placeholder pasted): comment it out
    if bad:
        e2 = e
        for m in bad:
            e2 = e2.replace(m.group(0), "# " + m.group(0) + "   (file not found - X3 routings used)", 1)
        changes.append((env, e2, None, f".env: LIVE_ORDERS_ROUTES points to a file that isn't there - commented out, "
                                       f"Live Orders uses the routings in Sage X3"))
        e = e2
    add = [f"{k}={v}" for k, v in want.items() if v and not re.search(rf"(?m)^{k}=", e)]
    if add:
        block = "\n# -- Live Orders (add_live_orders_to_portal.py) --\n" + "\n".join(add) + "\n"
        changes = [c for c in changes if c[0] != env]       # one write of .env with both changes
        changes.append((env, e + ("" if e.endswith("\n") or not e else "\n") + block, None,
                        ".env: " + "; ".join(add)))
    return changes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", default=r"C:\ClaudeVision\sdi-intelligence-backend")
    ap.add_argument("--runs", default=str(Path.home() / "SDI_X3_runs"))
    ap.add_argument("--share", default=r"\\sdi-dc01\shareddata$\Shared\Operations\Reporting\LiveOrders",
                    help="Production's workbook folder, as a network path (the service can't see K:)")
    ap.add_argument("--share-user", default=r"K:\Operations\Reporting\LiveOrders", help="the same folder as people see it")
    ap.add_argument("--routes-file", default="", help="optional: a route load file; default is X3 routings")
    ap.add_argument("--x3-config", default=str(Path.home() / ".sdi" / "x3_api.json"),
                    help="the read-only X3 API settings (the service runs as another account, so give the full path)")
    ap.add_argument("--exports", default=str(Path.home() / "SDI_X3_exports"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    target = Path(a.target)
    try:                                                    # Live Orders runs with THIS Python (LIVE_ORDERS_PYTHON)
        import openpyxl  # noqa: F401
    except ImportError:
        print(f"WARNING: {sys.executable} has no openpyxl - Regenerate will fail until you run:\n"
              f'    "{sys.executable}" -s -m pip install openpyxl\n  (in PowerShell as administrator; -s skips your own user folder, '
              f'so it installs where the service can see it)')
    changes = plan(target, a.runs, a)
    if not changes:
        print("Nothing to do - Live Orders is already in the portal.")
        return
    print(("APPLYING" if a.apply else "PREVIEW (nothing changed - add --apply to make these changes)") + f" in {target}:")
    for f, _, _, desc in changes:
        print("  -", desc)
    if not a.apply:
        return
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for f, text, src, desc in changes:
        if f.exists():
            shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}"))
        if src:
            shutil.copy2(src, f)
        else:
            f.write_text(text, encoding="utf-8")
    print(f"Done. Backups: *.bak-{stamp}. Now restart the SDIIntelligence service so app.py is re-read.")


if __name__ == "__main__":
    main()
