"""Give the standalone pages the portal's left-hand navigation.

THE PANEL VANISHING IS A NAVIGATION DEAD END. /estimating and /guide are served as their own
documents, so the portal's sidebar disappeared the moment an estimator opened either — and the
only way back was the browser's Back button. On the page people will use every day, that reads as
having left the system rather than moved within it.

The portal routes its views from the URL hash, so a link to /#files or /#tools from anywhere lands
on the right view. That is what lets a plain sidebar on a separate document behave like the real
one. Injected rather than copied by hand into each page, so the two cannot drift apart.

Idempotent: running it twice replaces the block rather than stacking a second copy.

    python _inject_sidebar.py
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = {
    "sdi-estimating-intelligence.html": "estimating",
    "sdi-estimating-guide.html": "guide",
}

START = "<!-- SDI-SIDEBAR:START -->"
END = "<!-- SDI-SIDEBAR:END -->"

# The plain mark app.py falls back to when the logo FILE is missing, as a data URI for when the
# ROUTE is missing. Kept byte-identical to _LOGO_FALLBACK in app.py so a page served by an older
# backend degrades to the same thing a current one would have given it, rather than to a hole.
_LOGO_FALLBACK_URI = (
    "data:image/svg+xml;charset=utf-8,"
    "%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E"
    "%3Ccircle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23e8a33d%22/%3E"
    "%3Ctext x=%2250%22 y=%2266%22 text-anchor=%22middle%22 "
    "font-family=%22Inter,Arial,sans-serif%22 font-weight=%22800%22 font-size=%2254%22 "
    "fill=%22%23000%22%3ES%3C/text%3E%3C/svg%3E"
)

# THE AI SERVICES, WHICH THE PORTAL RENDERS FROM JAVASCRIPT AND A COPIED SIDEBAR CANNOT.
#
# The first version of this nav carried Overview, Operate and Govern and stopped there — so on
# /estimating twenty-one entries simply were not present, which is most of the menu. They live in
# a SERVICES array the portal turns into links at load time; a static page has no such array, so
# they are listed here and kept in step by the check below, which fails loudly rather than letting
# the two drift apart in silence.
#
# Each links to the portal's own deep link for that service: /#aisvc-<id>.
def _services_from_the_portal():
    """The AI Services menu, read from the portal that defines it.

    THIS WAS A HAND-KEPT COPY AND IT DRIFTED, exactly as the check below had been warning. By
    17 Sep 2026 the portal carried SDI Technical Design Intelligence, SDI Drawing Search
    Intelligence and SDI Client Briefing Intelligence and this file did not, so both estimating
    pages shipped a menu three services short of the portal's -- and the entry they did share,
    Sage X3, was under an older name.

    A check that tells you two lists disagree is worth less than not having two lists. The
    portal's SERVICES array is the definition; this reads it, in order, so a service added
    there appears here the next time the injector runs and there is nothing to remember.
    """
    portal = HERE / "sdi-intelligence-portal.html"
    text = portal.read_text(encoding="utf-8")
    body = text[text.index("const SERVICES=["):]
    out = []
    for sid, name in re.findall(r"\{id:'([a-z0-9_-]+)',\s*name:'((?:[^'\\]|\\.)*)'", body):
        # The portal writes its names with JS escapes (\u00b7 for a middle dot). The sidebar is
        # HTML, so they are decoded here rather than pasted through as literal backslashes.
        out.append((sid, re.sub(r"\\u([0-9a-fA-F]{4})",
                                lambda m: chr(int(m.group(1), 16)), name).replace("&", "&amp;")))
    if not out:                                     # a parse that finds nothing is a bug, not an empty menu
        raise SystemExit("could not read SERVICES from the portal -- refusing to write an empty "
                         "AI Services menu")
    return out


AI_SERVICES = _services_from_the_portal()

# Every entry outside this pair of pages goes to the portal and names the view it wants.
NAV = [
    ("Overview", [("Dashboard", "/#dashboard", None)]),
    ("AI Services", [("Overview", "/#aisvc", None)]
                    + [(name, f"/#aisvc-{sid}", None) for sid, name in AI_SERVICES]),
    ("Operate", [
        ("SDI Estimating Intelligence", "/estimating", "estimating"),
        ("SDI Estimating Intelligence Guide", "/guide", "guide"),
        ("SDI Drawing Search Intelligence Guide", "/#fixture-guide", None),
        # The APPLICATION itself — Muhammad's drawing search, live on the UAT host — as
        # James asked for it: called exactly this, directly below its guide. An absolute
        # href is emitted with target=_blank (see _markup), so it opens in its own tab and
        # is never hijacked by the portal's hash router. Held HERE so that re-running this
        # injector can never wipe it from the copied sidebars again.
        ("SDI Drawing Search Intelligence", "http://LC-328802:5000/", None),
        ("SDI Estimating Intelligence Tools", "/#tools", None),
        ("Files &amp; Directories", "/#files", None),
        ("Status Reports", "/#reports", None),
        ("Go-Live Guide", "/#golive", None),
        ("Testing", "/#testing", None),
    ]),
    ("Govern", [
        # Permissions removed 25 Aug 2026 — it described a role model the portal does not enforce.
        ("Architecture", "/#architecture", None),
        ("R&amp;D Capture", "/#rnd", None),
        ("Servers", "/#servers", None),
        ("AI Programme", "/#programme", None),
    ]),
]

CSS = """
<style id="sdi-sidebar-css">
  /* The portal's own tokens are already defined on these pages, so this inherits the look. */
  :root{ --sdinav-w:250px; }
  body{ padding-left:var(--sdinav-w); }
  /* ── COLLAPSED ────────────────────────────────────────────────────────────────────
     The whole layout is already driven by --sdinav-w, so collapsing is one variable.
     These items carry no icons -- unlike the portal's rail, which collapses to icons --
     so there is nothing useful to show at 46px. It becomes a strip with the toggle on
     it: the screen goes back to the form, and one click brings the menu back. */
  body.nav-collapsed{ --sdinav-w:56px; }
  body.nav-collapsed .sdinav-grp,
  body.nav-collapsed .sdinav-item,
  body.nav-collapsed .sdinav-brand span{ display:none; }
  /* The word stays. An arrow alone asks the reader to work out which way it points and
     what that does; "Expand" does not. Stacked under the chevron, because it will not sit
     beside it at this width. */
  body.nav-collapsed .sdinav-toggle{ flex-direction:column; gap:4px; font-size:9px;
     letter-spacing:.08em; text-transform:uppercase; padding:10px 0 11px; }
  body.nav-collapsed .sdinav-brand{ padding:14px 0; justify-content:center; }
  body.nav-collapsed .sdinav-logo{ max-width:26px; }
  .sdinav{ display:flex; flex-direction:column; }
  .sdinav-body{ flex:1; }
  .sdinav-toggle{
    display:flex; align-items:center; gap:9px; width:100%;
    padding:10px 16px; border:0; border-top:1px solid var(--line);
    background:transparent; color:var(--muted); cursor:pointer;
    font-family:inherit; font-size:11.5px; letter-spacing:.04em; text-align:left;
    position:sticky; bottom:0; transition:.16s;
  }
  .sdinav-toggle:hover{ color:var(--ink); background:#ffffff08; }
  .sdinav-toggle:focus-visible{ outline:2px solid var(--brand); outline-offset:-2px; }
  body.nav-collapsed .sdinav-toggle{ justify-content:center; padding:10px 0; }
  .sdinav-toggle .chev{ width:14px; height:14px; flex:none; transition:transform .18s; }
  body.nav-collapsed .sdinav-toggle .chev{ transform:rotate(180deg); }
  /* LEFT-ALIGNED, not centred in what is left over. These pages centre their content with
     margin:0 auto, which was fine full-width and wrong once a 250px rail took the left of the
     screen: the content drifted toward the middle and sat away from the menu beside it. Keep the
     measure (long lines are hard to read) and pin it to the left instead. */
  .wrap{ margin-left:0 !important; margin-right:auto !important; }
  .sdinav{
    position:fixed; left:0; top:0; bottom:0; width:var(--sdinav-w); overflow-y:auto;
    background:var(--panel); border-right:1px solid var(--line);
    z-index:900; padding-bottom:24px;
  }
  .sdinav-brand{ display:flex; align-items:center; gap:10px; padding:18px 16px 16px;
    text-decoration:none; color:inherit; }
  .sdinav-mark{ width:30px; height:30px; border-radius:7px; background:var(--brand);
    /* #000, as the portal's own .mark b uses, and NOT the near-black palette literal:
       the mark sits on amber in both themes, so its ink is not theme-dependent, and a
       palette literal here is one no [data-theme] rule can reach. The pages had been
       hand-corrected for that once already and re-running this file undid it. */
    color:#000; font-weight:900; font-size:17px; display:flex; align-items:center;
    justify-content:center; font-family:var(--disp,'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif); }
  /* we.are.sdi, served by /api/brand/logo from the SAME folder the client quote reads. The
     lettered .sdinav-mark above is only the fallback for a page opened off the share, where
     there is no backend to ask. */
  .sdinav-logo{ height:24px; width:auto; max-width:70px; display:block; flex:none; }
  .sdinav-brand b{ font-family:var(--disp,'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif); font-size:12.5px;
    letter-spacing:.02em; display:block; line-height:1.15; white-space:nowrap; }
  .sdinav-brand span{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.14em;
    color:var(--dim); display:block; }
  .sdinav-grp{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.16em;
    text-transform:uppercase; color:var(--dim); padding:16px 16px 6px; }
  .sdinav a.sdinav-item{ display:block; padding:8px 16px; color:var(--muted);
    text-decoration:none; font-size:13.5px; border-left:2px solid transparent; }
  .sdinav .sdinav-ext{ opacity:.55; font-size:.9em; }
  .sdinav a.sdinav-item:hover{ color:var(--ink); background:#ffffff08; }
  .sdinav a.sdinav-item.is-here{ color:var(--ink); border-left-color:var(--brand);
    background:#ffffff0a; font-weight:600; }
  @media (max-width:900px){
    body{ padding-left:0; }
    .sdinav{ position:static; width:auto; height:auto; border-right:0;
      border-bottom:1px solid var(--line); }
  }
</style>
"""


def _markup(current: str) -> str:
    out = [START, CSS, '<nav class="sdinav" aria-label="SDI Intelligence">',
           '  <a class="sdinav-brand" href="/">',
           # Same plain mark app.py serves when the logo file is missing. /api/brand/logo never
           # 404s on a backend that HAS the route; served by an older one it does, and the rail
           # shows a hole. onerror is cleared first so a failure here cannot loop.
           '    <img class="sdinav-logo" src="/api/brand/logo" alt="we.are.sdi"'
           ' onerror="this.onerror=null;this.src=\'' + _LOGO_FALLBACK_URI + '\'">',
           '    <span><b>SDI INTELLIGENCE</b><span>WE.ARE.SDI</span></span>',
           '  </a>',
           # The items live in their own box so the toggle can sit beneath them and stay
           # at the bottom of a rail that scrolls.
           '  <div class="sdinav-body">']
    for group, items in NAV:
        out.append(f'  <div class="sdinav-grp">{group}</div>')
        for label, href, key in items:
            here = " is-here" if key and key == current else ""
            if href.startswith("http"):
                # An external application, not a page of this site: its own tab, and a
                # muted launch mark so it cannot be mistaken for the guide above it.
                out.append(
                    f'  <a class="sdinav-item{here}" href="{href}" target="_blank" '
                    f'rel="noopener" title="Open the drawing search application '
                    f'(UAT host LC-328802:5000)">{label}'
                    f'<span class="sdinav-ext" aria-hidden="true"> ↗</span></a>')
                continue
            out.append(f'  <a class="sdinav-item{here}" href="{href}">{label}</a>')
    out += [
        '</div>',
        '<button class="sdinav-toggle" id="sdinav-toggle" type="button"',
        '        aria-label="Collapse the navigation" aria-expanded="true">',
        '  <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"',
        '       stroke-width="2" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>',
        '  <span>Collapse</span>',
        '</button>',
        '</nav>',
        # Remembered per browser. Wrapped, because a private window or a policy blocking site
        # data throws on access, and a menu that will not render over a cosmetic setting is a
        # bad trade. Titles are set before anything is hidden so the strip still explains
        # itself on hover.
        '<script>(function(){',
        '  var b=document.body, t=document.getElementById("sdinav-toggle"), K="sdi.nav.collapsed";',
        '  if(!t) return;',
        '  document.querySelectorAll(".sdinav-item").forEach(function(a){',
        '    var s=(a.textContent||"").trim(); if(s && !a.title) a.title=s; });',
        '  function set(on){',
        '    b.classList.toggle("nav-collapsed", on);',
        '    t.setAttribute("aria-expanded", String(!on));',
        '    t.setAttribute("aria-label", on ? "Expand the navigation" : "Collapse the navigation");',
        '    t.title = on ? "Expand the navigation" : "Collapse the navigation";',
        '    var l=t.querySelector("span"); if(l) l.textContent = on ? "Expand" : "Collapse";',
        '    try{ localStorage.setItem(K, on?"1":"0"); }catch(e){}',
        '  }',
        '  var start=false; try{ start = localStorage.getItem(K)==="1"; }catch(e){}',
        '  if(start) set(true);',
        '  t.addEventListener("click", function(){ set(!b.classList.contains("nav-collapsed")); });',
        '})();</script>',
        END,
    ]
    return "\n".join(out) + "\n"


def _check_services_match_the_portal() -> None:
    """Kept as a guard rather than a comparison. AI_SERVICES is now READ from the portal, so
    the two cannot disagree; what can still go wrong is the parse silently matching nothing
    after somebody reformats that array. Print what was read, so a menu that lost its services
    is visible in the run rather than in the browser."""
    print(f"  AI Services read from the portal: {len(AI_SERVICES)} "
          f"({', '.join(sid for sid, _ in AI_SERVICES[:4])}, ...)")



def main() -> None:
    _check_services_match_the_portal()
    for name, key in PAGES.items():
        path = HERE / name
        if not path.exists():
            print(f"  SKIP  {name} (not found)")
            continue
        html = path.read_text(encoding="utf-8")
        block = _markup(key)
        if START in html and END in html:
            before, rest = html.split(START, 1)
            _, after = rest.split(END, 1)
            html = before + block.rstrip("\n") + after
            action = "updated"
        else:
            marker = "<body>"
            if marker not in html:
                print(f"  SKIP  {name} (no <body>)")
                continue
            html = html.replace(marker, marker + "\n" + block, 1)
            action = "inserted"
        path.write_text(html, encoding="utf-8")
        print(f"  {action}  {name}")


if __name__ == "__main__":
    main()
