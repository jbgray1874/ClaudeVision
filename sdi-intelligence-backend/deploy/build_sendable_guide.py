"""Build the sendable copy of the AM CRM user guide, from the live one.

    python deploy/build_sendable_guide.py <screenshot-dir> <output.html>

── WHY GENERATED AND NOT WRITTEN ────────────────────────────────────────────
The guide people are sent and the guide on the portal have to say the same
thing. Written twice they drift, and the one in somebody's inbox is the copy
nobody remembers to update - so it is the one that is wrong in six months,
quoted back at you, with your name on it.

So appportal/guide-am-crm.html stays the single source, and this makes the
sendable copy from it:

  * the portal chrome comes off ("Back to the app", "All apps" go nowhere
    from an inbox);
  * the screenshots go in, as data URIs, so it is ONE file that survives
    being forwarded - a guide whose images live on an intranet server shows
    broken boxes to everybody outside it;
  * a line at the top says what it is and that the figures are samples.

Run it again after editing the guide. It is deterministic.
"""
import base64
import mimetypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUIDE = HERE.parent / "appportal" / "guide-am-crm.html"

# Where each screenshot goes, and what it is there to show. Keyed on the
# section heading it follows, so adding a section cannot silently orphan one.
PLACED = [
    ("start", "01-portal-card.png",
     "The card on the app portal. <b>Open SDI Intelligence AM CRM</b> starts the "
     "app; <b>User guide</b> opens this document."),
    ("ask", "02-app-phone.png",
     "The app on a phone. Your own records are listed underneath, newest "
     "question first."),
    ("change", "03-app-records.png",
     "A record as the app shows it, with the fields it can change."),
]

BANNER = """
<div class="sendable-note">
  <b>SDI Intelligence AM CRM — user guide.</b>
  This is the same guide that opens from the app portal, saved as a single file
  so it can be forwarded. The screenshots use <b>sample accounts and figures</b>
  for illustration; they are not live tracker data.
</div>
"""

STYLE = """
<style>
  .sendable-note{max-width:760px;margin:18px auto 0;padding:13px 15px;
    border:1px solid var(--line);border-left:3px solid var(--accent);
    border-radius:0 var(--r) var(--r) 0;background:var(--surface);
    color:var(--ink-dim);font-size:14px;line-height:1.55}
  figure.shot{margin:18px 0 22px}
  figure.shot img{width:100%;height:auto;display:block;border:1px solid var(--line);
    border-radius:var(--r);background:var(--surface)}
  figure.shot figcaption{margin-top:8px;color:var(--ink-faint);font-size:13px;
    line-height:1.5}
</style>
"""


def data_uri(path: Path) -> str:
    kind = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build(shots: Path, out: Path) -> int:
    html = GUIDE.read_text(encoding="utf-8")

    # 1. The portal chrome. Both links are relative to the portal and are dead
    #    ends from an inbox, so the whole bar goes.
    start = html.index('<div class="top">')
    end = html.index("</div>", html.index('<a href="./">All apps</a>')) + len("</div>")
    html = html[:start] + html[end:]

    # 2. Say what it is, before anything else.
    html = html.replace("<style>", STYLE + "<style>", 1)
    html = html.replace('<div class="wrap">', BANNER + '<div class="wrap">', 1)

    # 3. The screenshots, each after the section it illustrates.
    missing = []
    for anchor, filename, caption in PLACED:
        image = shots / filename
        if not image.is_file():
            missing.append(filename)
            continue
        marker = f'<h2 id="{anchor}"'
        if marker not in html:
            missing.append(f"section #{anchor} (the guide's headings changed)")
            continue
        # After the heading's closing tag, so the picture follows the title
        # rather than splitting it from its own text.
        at = html.index("</h2>", html.index(marker)) + len("</h2>")
        figure = (f'\n<figure class="shot"><img alt="{caption}" '
                  f'src="{data_uri(image)}">'
                  f'<figcaption>{caption}</figcaption></figure>\n')
        html = html[:at] + figure + html[at:]

    if missing:
        print("NOT BUILT. Missing:", ", ".join(missing), file=sys.stderr)
        return 1

    html = html.replace("<title>AM CRM guide · SDI Intelligence</title>",
                        "<title>SDI Intelligence AM CRM — user guide</title>", 1)
    out.write_text(html, encoding="utf-8")
    print(f"{out}  ({out.stat().st_size // 1024} KB, {len(PLACED)} screenshots embedded)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(build(Path(sys.argv[1]), Path(sys.argv[2])))
