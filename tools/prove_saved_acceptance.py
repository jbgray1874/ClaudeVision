"""Read-only proof of a saved run: its ledger re-audited against its calculated workbook, the
persisted release record, and the e-mail's projection of both (Programme Robust, D-598).

    python tools/prove_saved_acceptance.py output/json/<job>.json <matching.xlsx> [--out audit.json]

Never regenerates prices, calls a model, edits a workbook or changes release status. The
workbook must be the one the record's own audit hashed: an unmatched pair proves nothing.
Exit 0 only where the pair matches, the ledger passes and the release is not a draft with
nothing outstanding; exit 2 means acceptance is not demonstrated, not that the tool failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record", type=Path)
    ap.add_argument("workbook", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    # A PATH WITH A STRAY NEWLINE OR SPACE IS THE PATH (a wrapped PowerShell line).
    args.record, args.workbook = Path(str(args.record).strip()), Path(str(args.workbook).strip())
    args.out = Path(str(args.out).strip()) if args.out else None
    for what, given in (("record", args.record), ("workbook", args.workbook)):
        if not given.is_file():
            print(f"The {what} is not there: {given} — nothing was audited.")
            return 2
    from final_charge_contract import snapshot_xlsx
    from read_charge_contract import LEDGER_CHECK_CODES, audit
    from robust_ownership import release_email_lines

    summary = json.loads(args.record.read_text(encoding="utf-8-sig"))
    result = audit(summary, snapshot_xlsx(args.workbook))
    saved = summary.get("read_charge_result") or {}
    sha = hashlib.sha256(args.workbook.read_bytes()).hexdigest()
    paired = saved.get("workbook_sha256") == sha
    record = summary.get("costed_job") or {}
    release = record.get("release") or {}
    inv = summary.get("invariants") if isinstance(summary.get("invariants"), dict) else {}
    ledger_v = [v for v in (inv.get("violations") or []) if isinstance(v, dict)
                and v.get("check") == "check_what_the_read_returned_is_accounted_for"]
    # WHICH OF THE SAVED RELEASE'S OWN ROWS WERE THE LEDGER'S (review of D-598): read from the
    # rows the record persisted, not recomputed — the attribution a record made before
    # read_ledger_holds existed can still give.
    saved_rows = [d for d in (record.get("decisions_required") or []) if isinstance(d, dict)
                  and d.get("kind") == "consistency_check"]
    ledger_rows = [d for d in saved_rows if str(d.get("check_code") or "") in LEDGER_CHECK_CODES]
    accepted = bool(paired and result.get("applicable") and result.get("passed")
                    and release and release.get("outstanding") == 0
                    and release.get("draft") is False)
    report = {"record": str(args.record), "workbook": str(args.workbook),
              "workbook_sha256": sha, "matches_saved_audit_hash": paired,
              "audit": result, "persisted_release": release,
              "saved_ledger_findings": [{"code": v.get("code"), "severity": v.get("severity")}
                                        for v in ledger_v],
              "saved_release_rows": {"blocking": len(saved_rows),
                                     "from_the_ledger": [{"check_code": d.get("check_code"),
                                                          "issue": d.get("issue")}
                                                         for d in ledger_rows]},
              "email_projection": release_email_lines(record, dict(summary,
                                                                   read_charge_result=result)),
              "accepted": accepted,
              "scope": ("audit and e-mail projection only; does not prove a regenerated e-mail "
                        "or the live publication gate")}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"paired": paired, "accepted": accepted,
                      "issues": len(result.get("issues") or []),
                      "saved_ledger_findings": len(ledger_v),
                      "saved_release_rows": len(saved_rows),
                      "of_them_the_ledgers": len(ledger_rows),
                      "status": release.get("status"), "draft": release.get("draft"),
                      "read_ledger_holds": release.get("read_ledger_holds"),
                      "out": str(args.out) if args.out else None}))
    return 0 if accepted else 2


if __name__ == "__main__":
    sys.exit(main())
