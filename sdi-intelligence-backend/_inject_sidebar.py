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

from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = {
    "sdi-estimating-intelligence.html": "estimating",
    "sdi-estimating-guide.html": "guide",
}

START = "<!-- SDI-SIDEBAR:START -->"
END = "<!-- SDI-SIDEBAR:END -->"

# THE AI SERVICES, WHICH THE PORTAL RENDERS FROM JAVASCRIPT AND A COPIED SIDEBAR CANNOT.
#
# The first version of this nav carried Overview, Operate and Govern and stopped there — so on
# /estimating twenty-one entries simply were not present, which is most of the menu. They live in
# a SERVICES array the portal turns into links at load time; a static page has no such array, so
# they are listed here and kept in step by the check below, which fails loudly rather than letting
# the two drift apart in silence.
#
# Each links to the portal's own deep link for that service: /#aisvc-<id>.
AI_SERVICES = [
    ("estimating", "Estimating"),
    ("brief", "AI Brief Capture &amp; Concept Design"),
    ("omniverse", "Design Omniverse · Immersive"),
    ("dfm", "AI Design for Manufacture"),
    ("scheduling", "AI Production Scheduling"),
    ("manufacture", "AI Manufacture &amp; Robotics"),
    ("inspection", "AI Quality Inspection"),
    ("md-agent", "MD Agent · Chief of Staff"),
    ("sales-agent", "Sales Intelligence Agent"),
    ("design-agent", "Design Support Agent"),
    ("production-agent", "Production Control Agent"),
    ("finance-agent", "Finance Intelligence Agent"),
    ("chatbots", "ChatBots · Customer &amp; Internal"),
    ("voice", "AI Voice Agents"),
    ("brighthr", "BrightHR Ingestion → InVentry"),
    ("wearesdi", "WeAreSDI · Public-Site AI Layer"),
    ("x3", "Sage X3 Acceleration Program"),
    ("obs", "OBS Studio · Live Recording"),
    ("tech-radar", "AI Tech Radar"),
    ("roadmap", "AI Roadmap"),
]

# Every entry outside this pair of pages goes to the portal and names the view it wants.
NAV = [
    ("Overview", [("Dashboard", "/#dashboard", None)]),
    ("AI Services", [("Overview", "/#aisvc", None)]
                    + [(name, f"/#aisvc-{sid}", None) for sid, name in AI_SERVICES]),
    ("Operate", [
        ("Estimating Intelligence", "/estimating", "estimating"),
        ("SDI Estimating Intelligence Guide", "/guide", "guide"),
        ("AI Tools", "/#tools", None),
        ("Files &amp; Directories", "/#files", None),
        ("Status Reports", "/#reports", None),
        ("Go-Live Guide", "/#golive", None),
        ("Testing", "/#testing", None),
    ]),
    ("Govern", [
        ("Permissions", "/#permissions", None),
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
  body.nav-collapsed{ --sdinav-w:46px; }
  body.nav-collapsed .sdinav-grp,
  body.nav-collapsed .sdinav-item,
  body.nav-collapsed .sdinav-brand span,
  body.nav-collapsed .sdinav-toggle span{ display:none; }
  body.nav-collapsed .sdinav-brand{ padding:14px 0; justify-content:center; }
  body.nav-collapsed .sdinav-logo{ max-width:26px; }
  .sdinav{ display:flex; flex-direction:column; }
  .sdinav-body{ flex:1; }
  .sdinav-toggle{
    display:flex; align-items:center; gap:9px; width:100%;
    padding:10px 16px; border:0; border-top:1px solid var(--line,#26262b);
    background:transparent; color:var(--muted,#9b9ba3); cursor:pointer;
    font-family:inherit; font-size:11.5px; letter-spacing:.04em; text-align:left;
    position:sticky; bottom:0; transition:.16s;
  }
  .sdinav-toggle:hover{ color:var(--ink,#f0efec); background:#ffffff08; }
  .sdinav-toggle:focus-visible{ outline:2px solid var(--brand,#e8a33d); outline-offset:-2px; }
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
    background:var(--panel,#121214); border-right:1px solid var(--line,#26262b);
    z-index:900; padding-bottom:24px;
  }
  .sdinav-brand{ display:flex; align-items:center; gap:10px; padding:18px 16px 16px;
    text-decoration:none; color:inherit; }
  .sdinav-mark{ width:30px; height:30px; border-radius:7px; background:var(--brand,#e8a33d);
    color:#0d0d0f; font-weight:900; font-size:17px; display:flex; align-items:center;
    justify-content:center; font-family:var(--disp,'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif); }
  /* we.are.sdi, served by /api/brand/logo from the SAME folder the client quote reads. The
     lettered .sdinav-mark above is only the fallback for a page opened off the share, where
     there is no backend to ask. */
  .sdinav-logo{ height:24px; width:auto; max-width:70px; display:block; flex:none; }
  .sdinav-brand b{ font-family:var(--disp,'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif); font-size:12.5px;
    letter-spacing:.02em; display:block; line-height:1.15; white-space:nowrap; }
  .sdinav-brand span{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.14em;
    color:var(--dim,#6a6a72); display:block; }
  .sdinav-grp{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.16em;
    text-transform:uppercase; color:var(--dim,#6a6a72); padding:16px 16px 6px; }
  .sdinav a.sdinav-item{ display:block; padding:8px 16px; color:var(--muted,#9b9ba3);
    text-decoration:none; font-size:13.5px; border-left:2px solid transparent; }
  .sdinav a.sdinav-item:hover{ color:var(--ink,#f0efec); background:#ffffff08; }
  .sdinav a.sdinav-item.is-here{ color:var(--ink,#f0efec); border-left-color:var(--brand,#e8a33d);
    background:#ffffff0a; font-weight:600; }
  @media (max-width:900px){
    body{ padding-left:0; }
    .sdinav{ position:static; width:auto; height:auto; border-right:0;
      border-bottom:1px solid var(--line,#26262b); }
  }
</style>
"""


def _markup(current: str) -> str:
    out = [START, CSS, '<nav class="sdinav" aria-label="SDI Intelligence">',
           '  <a class="sdinav-brand" href="/">',
           '    <img class="sdinav-logo" src="/api/brand/logo" alt="we.are.sdi">',
           '    <span><b>SDI INTELLIGENCE</b><span>WE.ARE.SDI</span></span>',
           '  </a>',
           # The items live in their own box so the toggle can sit beneath them and stay
           # at the bottom of a rail that scrolls.
           '  <div class="sdinav-body">']
    for group, items in NAV:
        out.append(f'  <div class="sdinav-grp">{group}</div>')
        for label, href, key in items:
            here = " is-here" if key and key == current else ""
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
        '    t.title = on ? "Expand" : "Collapse";',
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
    """The portal builds its AI Services links from a JavaScript array; this file lists them by
    hand. Two lists of the same thing drift, and the failure is silent — entries quietly missing
    from one page. Compare them and say so, loudly, rather than shipping a shorter menu."""
    import re
    portal = HERE / "sdi-intelligence-portal.html"
    if not portal.exists():
        return
    found = re.findall(r"id:'([a-z0-9_-]+)',\s*name:'(?:[^'\\]|\\.)*'",
                       portal.read_text(encoding="utf-8"))
    theirs, ours = set(found), {sid for sid, _ in AI_SERVICES}
    if theirs and theirs != ours:
        missing, extra = sorted(theirs - ours), sorted(ours - theirs)
        print("  ! AI Services list is out of step with the portal:")
        if missing:
            print(f"      missing here : {', '.join(missing)}")
        if extra:
            print(f"      not in portal: {', '.join(extra)}")
        print("      Update AI_SERVICES in this file, then re-run.")


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
