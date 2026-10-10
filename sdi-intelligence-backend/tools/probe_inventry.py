"""Prove the InVentry integration against the live system, one person at a time.

The push is all-or-nothing: the first --apply run signs in everyone BrightHR
says is on site, around 89 people. That is a poor first contact with a live
reception system, and a poor way to answer the questions we still have:

  * do the credentials work at all?
  * does AddPersonnelAction accept our ActionLocation, or refuse it?
  * does the marker come back as LastEventLocation, which is what makes
    automatic sign-out safe?

This answers all three with a blast radius of one record - and the one record
can be you.

    python tools/probe_inventry.py                          # read-only
    python tools/probe_inventry.py --find "James Gray"      # read-only
    python tools/probe_inventry.py --sign-in "James Gray" --confirm
    python tools/probe_inventry.py --sign-out "James Gray" --confirm

Nothing is written without both a name and --confirm. After a write it re-reads
the person and reports what InVentry actually stored, which is the only way to
learn whether the marker survived.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_config as cfg          # noqa: E402
import hr_inventry_api as api    # noqa: E402


def describe(record):
    return {
        "ID": api.inventry_id(record),
        "name": f"{api._field(record, 'FirstName')} {api._field(record, 'Surname')}".strip(),
        "email": api._field(record, "EmailAddress"),
        "PersonID": api.person_key(record),
        "LastActivity": api._field(record, "LastActivity"),
        "LastActivityDate": api._field(record, "LastActivityDate"),
        "LastEventLocation": api.last_location(record),
        "on_site": api.is_on_site(record),
        "signed_in_by_us": api.signed_in_by_us(record),
    }


def find(people, needle):
    needle = needle.strip().lower()
    hits = []
    for r in people:
        name = f"{api._field(r, 'FirstName')} {api._field(r, 'Surname')}".strip().lower()
        if needle in name or needle == api._field(r, "EmailAddress").strip().lower():
            hits.append(r)
    return hits


def one(people, needle):
    """Exactly one match, or stop. Never guess which person to write to."""
    hits = find(people, needle)
    if not hits:
        sys.exit(f"No InVentry record matches {needle!r}. Try --find with less of the name.")
    if len(hits) > 1:
        print(f"{len(hits)} records match {needle!r} - be more specific:")
        for r in hits:
            print("  ", json.dumps(describe(r)))
        sys.exit(1)
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--find", metavar="NAME", help="show matching records, write nothing")
    # One write per run. Both together used to do the sign-in and silently
    # ignore the sign-out.
    write = ap.add_mutually_exclusive_group()
    write.add_argument("--sign-in", metavar="NAME")
    write.add_argument("--sign-out", metavar="NAME")
    ap.add_argument("--confirm", action="store_true",
                    help="required for any write - this is a live reception system")
    args = ap.parse_args()

    # Said before anything else: a setting added to the wrong worktree's .env
    # is indistinguishable from a setting that did not work.
    print(f"settings from: {cfg.ENV_FILE}"
          f"{'' if cfg.ENV_FILE_FOUND else '   <-- DOES NOT EXIST'}")
    print(f"  base_url  {cfg.INVENTRY_API_BASE_URL or '(unset)'}")
    print(f"  ca_bundle {cfg.INVENTRY_API_CA_BUNDLE or '(unset)'}")
    print(f"  check_hostname {cfg.INVENTRY_API_CHECK_HOSTNAME}\n")

    client = api.InVentryAPI()

    # Credentials first. Everything else is noise until this passes.
    try:
        print(json.dumps(client.check(), indent=2))
    except api.InVentryAPIError as exc:
        sys.exit(f"\nFAILED: {exc}\n\nNothing else will work until this does.")

    target = args.sign_in or args.sign_out
    if not (args.find or target):
        return

    people = client.get_personnel()

    if args.find:
        hits = find(people, args.find)
        print(f"\n{len(hits)} match(es) for {args.find!r}:")
        for r in hits:
            print(json.dumps(describe(r), indent=2))
        if not target:
            return

    record = one(people, target)
    before = describe(record)
    action = "SIGN IN" if args.sign_in else "SIGN OUT"

    print(f"\n{action}  {before['name']}  (InVentry ID {before['ID']})")
    print(f"  currently: LastActivity={before['LastActivity']!r} "
          f"LastEventLocation={before['LastEventLocation']!r}")
    print(f"  will send: ActionLocation={cfg.INVENTRY_ACTION_LOCATION!r}")

    if not args.confirm:
        print("\nDry run. Re-run with --confirm to actually write this.")
        return

    ident = before["ID"]
    if args.sign_in:
        client.sign_in(ident)
    else:
        client.sign_out(ident)
    print("  sent.")

    # Re-read. What InVentry stored is the only answer that counts - a 200 on
    # the POST does not prove the location survived.
    after = describe(one(client.get_personnel(), target))
    print("\nInVentry now reports:")
    print(json.dumps(after, indent=2))

    print("\nWhat this tells us:")
    if client.action_location_dropped:
        print("  * ActionLocation was REFUSED. The client dropped it and the action still")
        print("    went through - so sign-ins are safe, but automatic sign-out cannot be")
        print("    enabled: there is no marker to recognise our own writes by.")
    elif after["signed_in_by_us"]:
        print("  * The marker round-tripped as LastEventLocation. Automatic sign-out is")
        print("    safe to enable (INVENTRY_ENABLE_SIGN_OUT=true) once you are happy.")
    elif after["LastEventLocation"]:
        print(f"  * Accepted, but stored as {after['LastEventLocation']!r} rather than our")
        print("    marker. Set INVENTRY_ACTION_LOCATION to that value, or leave sign-out off.")
    else:
        print("  * Accepted and discarded - no LastEventLocation came back. Sign-ins work;")
        print("    automatic sign-out must stay off, as we cannot recognise our own writes.")

    for w in client.warnings:
        print(f"\nwarning: {w}")


if __name__ == "__main__":
    main()
