"""Who has forgotten to clock out on BrightHR, for HR to correct.

A Blip clocking left open is not just a gap in InVentry: BrightHR is the record
of hours, and an open clocking is an hours record that is wrong until someone
closes it. The sync already ignores clockings open longer than
BLIP_MAX_CLOCKIN_AGE_HOURS (20h); this lists them so they get fixed at source.

    python tools/forgotten_clockouts.py            # print the list
    python tools/forgotten_clockouts.py --send     # and email it to SDI_HR_REPORT_TO

Runs a fresh BrightHR check first. Changes nothing in BrightHR or InVentry.
Meant to run weekly from Task Scheduler with --send.
"""
import datetime
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_blip                   # noqa: E402
import hr_config as cfg          # noqa: E402


def forgotten(snapshot: dict, now=None, max_age_hours=None) -> list:
    """Open clockings older than the limit, oldest first."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    limit = cfg.BLIP_MAX_CLOCKIN_AGE_HOURS if max_age_hours is None else max_age_hours
    out = []
    for r in snapshot.get("on_site") or []:
        start = (r.get("clocking") or {}).get("start") or ""
        try:
            t = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        hours = (now - t).total_seconds() / 3600
        if hours > limit:
            out.append({"name": f"{r.get('first_name', '')} {r.get('surname', '')}".strip() or "?",
                        "clocked_in": t, "days": hours / 24})
    return sorted(out, key=lambda x: x["clocked_in"])


def compose(rows: list, checked_at: str) -> tuple:
    subject = (f"Forgotten BrightHR clock-outs: {len(rows)} "
               f"{'person' if len(rows) == 1 else 'people'}")
    intro = ("These people are still clocked in on BrightHR Blip from a previous shift. "
             "Their hours in BrightHR are wrong until the clocking is closed with the time "
             "they actually left. They are not counted as on site for the fire roll call.")
    text = [intro, "", f"Checked {checked_at[:16].replace('T', ' ')} UTC", ""]
    text += [f"  {r['name']:<32} clocked in {r['clocked_in']:%d %b %Y %H:%M}  "
             f"({r['days']:.0f} days open)" for r in rows]
    body = "".join(f"<tr><td>{html.escape(r['name'])}</td>"
                   f"<td>{r['clocked_in']:%d %b %Y %H:%M}</td><td>{r['days']:.0f}</td></tr>"
                   for r in rows)
    page = (f"<p>{html.escape(intro)}</p><p>Checked {html.escape(checked_at[:16].replace('T', ' '))} UTC</p>"
            "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse:collapse'>"
            "<tr><th align='left'>Name</th><th align='left'>Clocked in (UTC)</th>"
            f"<th align='left'>Days open</th></tr>{body}</table>")
    return subject, page, "\n".join(text)


def main(argv) -> int:
    summary = hr_blip.run_blip()
    if summary.get("status") == "busy":
        print("A BrightHR check is already running; try again in a few minutes.")
        return 2
    snap = json.loads((Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json").read_text(encoding="utf-8"))
    rows = forgotten(snap)
    subject, page, text = compose(rows, summary.get("timestamp") or "")
    print(subject)
    print(text)
    if "--send" not in argv:
        return 0
    if not rows:
        print("Nobody to report; nothing sent.")
        return 0
    if not cfg.HR_REPORT_TO:
        print("SDI_HR_REPORT_TO is not set in .env; nothing sent.")
        return 2
    import estimate_email      # the SDI Intelligence mailbox, as the estimate emails use
    result = estimate_email.send(sorted(cfg.HR_REPORT_TO), subject, page, text)
    print("sent" if result.get("sent") else f"NOT sent: {result.get('reason')}")
    return 0 if result.get("sent") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
