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

# Every entry outside this pair of pages goes to the portal and names the view it wants.
NAV = [
    ("Overview", [("Dashboard", "/#dashboard", None)]),
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
  .sdinav{
    position:fixed; left:0; top:0; bottom:0; width:var(--sdinav-w); overflow-y:auto;
    background:var(--panel,#17171b); border-right:1px solid var(--line,#2a2a31);
    z-index:900; padding-bottom:24px;
  }
  .sdinav-brand{ display:flex; align-items:center; gap:10px; padding:18px 16px 16px;
    text-decoration:none; color:inherit; }
  .sdinav-mark{ width:30px; height:30px; border-radius:7px; background:var(--brand,#ffd400);
    color:#141417; font-weight:900; font-size:17px; display:flex; align-items:center;
    justify-content:center; font-family:var(--disp,'Archivo',sans-serif); }
  .sdinav-brand b{ font-family:var(--disp,'Archivo',sans-serif); font-size:13.5px;
    letter-spacing:.02em; display:block; line-height:1.15; }
  .sdinav-brand span{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.14em;
    color:var(--dim,#6b6b73); display:block; }
  .sdinav-grp{ font-family:var(--mono,monospace); font-size:9.5px; letter-spacing:.16em;
    text-transform:uppercase; color:var(--dim,#6b6b73); padding:16px 16px 6px; }
  .sdinav a.sdinav-item{ display:block; padding:8px 16px; color:var(--muted,#a3a3aa);
    text-decoration:none; font-size:13.5px; border-left:2px solid transparent; }
  .sdinav a.sdinav-item:hover{ color:var(--ink,#f3f2ee); background:#ffffff08; }
  .sdinav a.sdinav-item.is-here{ color:var(--ink,#f3f2ee); border-left-color:var(--brand,#ffd400);
    background:#ffffff0a; font-weight:600; }
  @media (max-width:900px){
    body{ padding-left:0; }
    .sdinav{ position:static; width:auto; height:auto; border-right:0;
      border-bottom:1px solid var(--line,#2a2a31); }
  }
</style>
"""


def _markup(current: str) -> str:
    out = [START, CSS, '<nav class="sdinav" aria-label="SDI Intelligence">',
           '  <a class="sdinav-brand" href="/">',
           '    <span class="sdinav-mark">S</span>',
           '    <span><b>INTELLIGENCE</b><span>WE.ARE.SDI</span></span>',
           '  </a>']
    for group, items in NAV:
        out.append(f'  <div class="sdinav-grp">{group}</div>')
        for label, href, key in items:
            here = " is-here" if key and key == current else ""
            out.append(f'  <a class="sdinav-item{here}" href="{href}">{label}</a>')
    out += ['</nav>', END]
    return "\n".join(out) + "\n"


def main() -> None:
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
