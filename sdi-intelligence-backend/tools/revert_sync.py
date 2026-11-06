"""Undo the sync: sign out everyone it has signed in.

Lists every InVentry record currently on site whose last event carries the
sync's marker (INVENTRY_ACTION_LOCATION) - people the sync signed in, whom
nobody has since signed in or out at reception - and with --confirm signs
them all out.

A record signed in at reception never carries the marker, so it is never
touched. This is the same rule that makes automatic sign-out safe.

Disable the scheduled task FIRST. Otherwise its next cycle signs anyone still
clocked in on BrightHR straight back in.

    python tools/revert_sync.py            # list only, writes nothing
    python tools/revert_sync.py --confirm  # sign them all out
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_config as cfg          # noqa: E402
import hr_inventry_api as api    # noqa: E402


def name(record):
    return f"{api._field(record, 'FirstName')} {api._field(record, 'Surname')}".strip() or "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true",
                    help="actually sign them out - this is a live reception system")
    args = ap.parse_args()

    marker = (cfg.INVENTRY_ACTION_LOCATION or "").strip()
    if not marker:
        sys.exit("INVENTRY_ACTION_LOCATION is empty, so the sync's sign-ins cannot be "
                 "told apart from reception's. Refusing to guess.")

    client = api.InVentryAPI()
    try:
        people = client.get_personnel()
    except api.InVentryAPIError as exc:
        sys.exit(f"FAILED: {exc}")

    ours = sorted((r for r in people if api.is_on_site(r) and api.signed_in_by_us(r)),
                  key=name)
    print(f"{len(ours)} person(s) on site, signed in by the sync "
          f"(last event {marker!r}):")
    for r in ours:
        print(f"  {name(r):<30} {api.inventry_id(r)}")

    if not ours:
        return
    if not args.confirm:
        print("\nList only - nothing written. Re-run with --confirm to sign them all out.")
        print("Disable the scheduled task first, or it will sign them back in.")
        return

    failed = 0
    for r in ours:
        try:
            client.sign_out(api.inventry_id(r))
            print(f"  signed out {name(r)}")
        except api.InVentryAPIError as exc:
            failed += 1
            print(f"  FAILED {name(r)}: {exc}")
    print(f"\nDone: {len(ours) - failed} signed out, {failed} failed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
