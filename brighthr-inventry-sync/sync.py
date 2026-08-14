"""BrightHR -> InVentry presence sync.

Reads who is clocked in on BrightHR Blip and makes InVentry's on-site register
match, so the fire roll call reflects who is actually in the building.

Runs in dry-run mode unless --apply is passed. Usage:

    python sync.py --check              # connectivity + config check, no writes
    python sync.py                      # dry run: log what would change
    python sync.py --apply              # write to InVentry
    python sync.py --apply --loop       # run every SYNC_INTERVAL_MINUTES

Safety rails (see SyncPlan.sign_out_blocked_reason): a BrightHR outage, an
empty response, or an implausibly large number of sign-outs suppresses the
sign-out half of the run rather than emptying the evacuation list.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from brighthr_client import BrightHRClient, BrightHRError, StaffPresence
from config import Config, ConfigError, load_config
from employee_map import EmployeeMap, EmployeeMapError
from inventry_client import InVentryClient, InVentryError, OnSiteRecord, build_inventry_client

log = logging.getLogger("sync")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PARTIAL = 2


# --------------------------------------------------------------------- logging


def setup_logging(config: Config, verbose: bool = False) -> None:
    """Console logging plus a daily rolling file, per the handover layout."""
    level = logging.DEBUG if verbose else getattr(logging, config.logging.level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        config.logging.log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            config.logging.log_path / "sync.log",
            when="midnight",
            backupCount=config.logging.retention_days,
            encoding="utf-8",
        )
        file_handler.suffix = "%Y%m%d"
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # A missing log directory must not stop the sync from running.
        log.warning("File logging disabled (%s): %s", config.logging.log_path, exc)


# ----------------------------------------------------------------- data model


@dataclass
class SyncAction:
    brighthr_id: str
    inventry_staff_id: str
    name: str = ""
    reason: str = ""


@dataclass
class SkippedItem:
    identifier: str
    name: str
    reason: str


@dataclass
class SyncPlan:
    to_sign_in: List[SyncAction] = field(default_factory=list)
    to_sign_out: List[SyncAction] = field(default_factory=list)
    skipped: List[SkippedItem] = field(default_factory=list)
    brighthr_on_site: int = 0
    inventry_on_site: int = 0
    # Set when a safety rail suppressed the sign-out half of the run.
    sign_out_blocked_reason: Optional[str] = None
    suppressed_sign_outs: List[SyncAction] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.to_sign_in and not self.to_sign_out

    def summary(self) -> str:
        parts = [
            f"BrightHR on site: {self.brighthr_on_site}",
            f"InVentry on site: {self.inventry_on_site}",
            f"sign in: {len(self.to_sign_in)}",
            f"sign out: {len(self.to_sign_out)}",
            f"skipped: {len(self.skipped)}",
        ]
        if self.sign_out_blocked_reason:
            parts.append(f"sign-outs SUPPRESSED ({len(self.suppressed_sign_outs)})")
        return " | ".join(parts)


@dataclass
class SyncResult:
    plan: SyncPlan
    signed_in: List[str] = field(default_factory=list)
    signed_out: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    dry_run: bool = True
    aborted_reason: Optional[str] = None

    @property
    def exit_code(self) -> int:
        if self.aborted_reason:
            return EXIT_ERROR
        if self.failures or self.plan.sign_out_blocked_reason:
            return EXIT_PARTIAL
        return EXIT_OK

    def to_dict(self) -> Dict[str, object]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "aborted_reason": self.aborted_reason,
            "brighthr_on_site": self.plan.brighthr_on_site,
            "inventry_on_site": self.plan.inventry_on_site,
            "signed_in": self.signed_in,
            "signed_out": self.signed_out,
            "skipped": [
                {"id": s.identifier, "name": s.name, "reason": s.reason} for s in self.plan.skipped
            ],
            "sign_out_blocked_reason": self.plan.sign_out_blocked_reason,
            "failures": self.failures,
        }


# ---------------------------------------------------------------- sync engine


class SyncEngine:
    def __init__(
        self,
        config: Config,
        brighthr: BrightHRClient,
        inventry: InVentryClient,
        employee_map: EmployeeMap,
    ) -> None:
        self.config = config
        self.brighthr = brighthr
        self.inventry = inventry
        self.employee_map = employee_map

    # -- planning ---------------------------------------------------------

    def build_plan(self) -> SyncPlan:
        """Work out what would change. Reads only; never writes."""
        presence = self.brighthr.get_clocked_in_staff(
            treat_break_as_on_site=self.config.sync.treat_break_as_on_site
        )
        on_site_records = self.inventry.get_on_site()

        absent_ids: Set[str] = set()
        if self.config.sync.check_absences:
            try:
                absent_ids = self.brighthr.get_absent_employee_ids()
            except BrightHRError as exc:
                # Absence data is a cross-check, not the source of truth, so a
                # failure here degrades to "no absences known" rather than
                # aborting the whole sync.
                log.warning("Could not read BrightHR absences, continuing without them: %s", exc)

        plan = SyncPlan(brighthr_on_site=len(presence), inventry_on_site=len(on_site_records))
        inventry_by_staff_id = {record.staff_id: record for record in on_site_records}

        expected_staff_ids = self._plan_sign_ins(plan, presence, absent_ids, inventry_by_staff_id)
        self._plan_sign_outs(plan, on_site_records, expected_staff_ids)
        self._apply_safety_rails(plan)
        return plan

    def _plan_sign_ins(
        self,
        plan: SyncPlan,
        presence: Sequence[StaffPresence],
        absent_ids: Set[str],
        inventry_by_staff_id: Dict[str, OnSiteRecord],
    ) -> Set[str]:
        """Queue arrivals; return the InVentry ids that should be on site."""
        expected: Set[str] = set()
        for person in presence:
            staff_id = self.employee_map.to_inventry(person.employee_id)
            if staff_id is None:
                # Unmapped: we cannot address this person in InVentry at all.
                plan.skipped.append(
                    SkippedItem(
                        identifier=person.employee_id,
                        name=person.employee_name,
                        reason="no InVentry staff id in employee_map.json",
                    )
                )
                continue

            expected.add(staff_id)

            if person.employee_id in absent_ids:
                # Clocked in but booked off: trust the absence record and leave
                # InVentry alone rather than signing in someone on holiday.
                plan.skipped.append(
                    SkippedItem(
                        identifier=person.employee_id,
                        name=person.employee_name,
                        reason="approved absence in BrightHR",
                    )
                )
                expected.discard(staff_id)
                continue

            if staff_id in inventry_by_staff_id:
                continue  # already on site in InVentry, nothing to do

            plan.to_sign_in.append(
                SyncAction(
                    brighthr_id=person.employee_id,
                    inventry_staff_id=staff_id,
                    name=person.employee_name or self.employee_map.name_for(person.employee_id),
                    reason=f"clocked in on BrightHR ({person.last_event_type or person.state})",
                )
            )
        return expected

    def _plan_sign_outs(
        self,
        plan: SyncPlan,
        on_site_records: Sequence[OnSiteRecord],
        expected_staff_ids: Set[str],
    ) -> None:
        for record in on_site_records:
            if record.staff_id in expected_staff_ids:
                continue

            brighthr_id = self.employee_map.to_brighthr(record.staff_id)
            if brighthr_id is None and not self.config.sync.sign_out_unmapped:
                # Someone InVentry knows about who is not in our map - a
                # visitor, contractor or a mapping gap. Not ours to sign out.
                plan.skipped.append(
                    SkippedItem(
                        identifier=record.staff_id,
                        name=record.staff_name,
                        reason="on site in InVentry but not in employee_map.json",
                    )
                )
                continue

            if self.config.sync.respect_manual_sign_in and not record.is_managed_by_sync(
                self.config.inventry.source_tag
            ):
                # Signed in at the InVentry terminal by a person, so a human
                # decision outranks ours.
                plan.skipped.append(
                    SkippedItem(
                        identifier=record.staff_id,
                        name=record.staff_name,
                        reason="manual InVentry sign-in, not signed in by this sync",
                    )
                )
                continue

            plan.to_sign_out.append(
                SyncAction(
                    brighthr_id=brighthr_id or "",
                    inventry_staff_id=record.staff_id,
                    name=record.staff_name,
                    reason="no longer clocked in on BrightHR",
                )
            )

    def _apply_safety_rails(self, plan: SyncPlan) -> None:
        """Suppress mass sign-outs that look like bad data rather than an empty site."""
        rails = self.config.sync
        reason: Optional[str] = None

        if plan.brighthr_on_site == 0 and plan.to_sign_out and not rails.allow_full_sign_out:
            reason = (
                "BrightHR reported nobody on site; treating as a data problem rather than an "
                "empty building (set SYNC_ALLOW_FULL_SIGN_OUT=true to override)"
            )
        elif len(plan.to_sign_out) > rails.max_sign_outs_per_run:
            reason = (
                f"{len(plan.to_sign_out)} sign-outs exceeds SYNC_MAX_SIGN_OUTS_PER_RUN "
                f"({rails.max_sign_outs_per_run})"
            )
        elif (
            plan.inventry_on_site > 0
            and len(plan.to_sign_out) / plan.inventry_on_site > rails.max_sign_out_ratio
        ):
            ratio = len(plan.to_sign_out) / plan.inventry_on_site
            reason = (
                f"{ratio:.0%} of InVentry's on-site register would be signed out, above "
                f"SYNC_MAX_SIGN_OUT_RATIO ({rails.max_sign_out_ratio:.0%})"
            )

        if reason:
            log.error("Sign-outs suppressed: %s", reason)
            plan.sign_out_blocked_reason = reason
            plan.suppressed_sign_outs = plan.to_sign_out
            plan.to_sign_out = []

    # -- execution --------------------------------------------------------

    def run(self, apply_changes: bool = False) -> SyncResult:
        started = time.monotonic()
        try:
            plan = self.build_plan()
        except BrightHRError as exc:
            # Presence unknown: make no changes at all. An outage must never
            # sign the building out.
            log.error("BrightHR unavailable, no changes made: %s", exc)
            return SyncResult(plan=SyncPlan(), dry_run=not apply_changes, aborted_reason=str(exc))
        except InVentryError as exc:
            log.error("InVentry unavailable, no changes made: %s", exc)
            return SyncResult(plan=SyncPlan(), dry_run=not apply_changes, aborted_reason=str(exc))

        result = SyncResult(plan=plan, dry_run=not apply_changes or self.inventry.is_read_only)
        log.info("Plan: %s", plan.summary())

        for action in plan.to_sign_in:
            label = f"{action.inventry_staff_id} ({action.name or action.brighthr_id})"
            if result.dry_run and not self.inventry.is_read_only:
                log.info("[DRY RUN] would SIGN IN  %s - %s", label, action.reason)
                result.signed_in.append(action.inventry_staff_id)
                continue
            try:
                self.inventry.sign_in(
                    staff_id=action.inventry_staff_id,
                    staff_name=action.name,
                    when=datetime.now(timezone.utc),
                    location=self.config.sync.site_name,
                )
                result.signed_in.append(action.inventry_staff_id)
                log.info("Signed in %s - %s", label, action.reason)
            except InVentryError as exc:
                log.error("Failed to sign in %s: %s", label, exc)
                result.failures.append(f"sign_in:{action.inventry_staff_id}: {exc}")

        for action in plan.to_sign_out:
            label = f"{action.inventry_staff_id} ({action.name or action.brighthr_id})"
            if result.dry_run and not self.inventry.is_read_only:
                log.info("[DRY RUN] would SIGN OUT %s - %s", label, action.reason)
                result.signed_out.append(action.inventry_staff_id)
                continue
            try:
                self.inventry.sign_out(action.inventry_staff_id, datetime.now(timezone.utc))
                result.signed_out.append(action.inventry_staff_id)
                log.info("Signed out %s - %s", label, action.reason)
            except InVentryError as exc:
                log.error("Failed to sign out %s: %s", label, exc)
                result.failures.append(f"sign_out:{action.inventry_staff_id}: {exc}")

        for item in plan.skipped:
            log.info("Skipped %s (%s): %s", item.identifier, item.name or "?", item.reason)

        log.info(
            "Sync %s in %.2fs: signed in %s, signed out %s, failures %s",
            "simulated" if result.dry_run else "applied",
            time.monotonic() - started,
            len(result.signed_in),
            len(result.signed_out),
            len(result.failures),
        )
        return result


# ------------------------------------------------------------------- wiring


def build_engine(config: Config, force_dry_run: bool) -> SyncEngine:
    config.validate_for_brighthr()
    if not force_dry_run:
        config.validate_for_write()
    brighthr = BrightHRClient(config.brighthr)
    inventry = build_inventry_client(config.inventry, force_dry_run=force_dry_run)
    employee_map = EmployeeMap.load(config.sync.employee_map_path)
    if len(employee_map) == 0:
        log.warning("Employee map is empty - no staff can be matched between the two systems yet.")
    return SyncEngine(config, brighthr, inventry, employee_map)


def run_check(config: Config) -> int:
    """Read-only connectivity and configuration check."""
    ok = True

    try:
        config.validate_for_brighthr()
        client = BrightHRClient(config.brighthr)
        presence = client.get_clocked_in_staff(
            treat_break_as_on_site=config.sync.treat_break_as_on_site
        )
        log.info("BrightHR OK - %s staff currently on site", len(presence))
        for person in presence[:10]:
            log.info(
                "  %s %s (%s since %s)",
                person.employee_id,
                person.employee_name or "?",
                person.state,
                person.since.isoformat() if person.since else "unknown",
            )
        if len(presence) > 10:
            log.info("  ... and %s more", len(presence) - 10)
    except (ConfigError, BrightHRError) as exc:
        log.error("BrightHR check FAILED: %s", exc)
        ok = False

    try:
        with build_inventry_client(config.inventry) as inventry:
            records = inventry.get_on_site()
            driver = "dry-run (no writes)" if inventry.is_read_only else config.inventry.driver
            log.info("InVentry OK via %s - %s staff on site", driver, len(records))
    except InVentryError as exc:
        log.error("InVentry check FAILED: %s", exc)
        ok = False

    try:
        employee_map = EmployeeMap.load(config.sync.employee_map_path)
        log.info("Employee map: %s mappings from %s", len(employee_map), config.sync.employee_map_path)
        if len(employee_map) == 0:
            log.warning("  no mappings yet - run tools/build_employee_map.py")
    except EmployeeMapError as exc:
        log.error("Employee map check FAILED: %s", exc)
        ok = False

    log.info("Check %s", "passed" if ok else "FAILED")
    return EXIT_OK if ok else EXIT_ERROR


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync BrightHR Blip clock-in data to InVentry.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to InVentry. Without this the sync only logs what it would do.",
    )
    parser.add_argument("--loop", action="store_true", help="Run continuously every SYNC_INTERVAL_MINUTES.")
    parser.add_argument("--check", action="store_true", help="Connectivity and config check, then exit.")
    parser.add_argument("--json-summary", type=Path, help="Write a JSON summary of the run to this path.")
    parser.add_argument("--env-file", type=Path, help="Path to a .env file (defaults to ./.env).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.env_file)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    setup_logging(config, verbose=args.verbose)

    if args.check:
        return run_check(config)

    try:
        engine = build_engine(config, force_dry_run=not args.apply)
    except (ConfigError, EmployeeMapError, BrightHRError, InVentryError) as exc:
        log.error("Startup failed: %s", exc)
        return EXIT_ERROR

    if not args.apply:
        log.info("DRY RUN - no changes will be written to InVentry. Pass --apply to write.")

    def run_once() -> SyncResult:
        result = engine.run(apply_changes=args.apply)
        if args.json_summary:
            args.json_summary.parent.mkdir(parents=True, exist_ok=True)
            args.json_summary.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return result

    if not args.loop:
        try:
            return run_once().exit_code
        finally:
            engine.inventry.close()

    interval = max(1, config.sync.interval_minutes) * 60
    log.info("Looping every %s minutes. Ctrl+C to stop.", config.sync.interval_minutes)
    try:
        while True:
            try:
                run_once()
            except Exception:  # keep the service alive across transient faults
                log.exception("Unhandled error during sync; continuing")
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Stopped.")
        return EXIT_OK
    finally:
        engine.inventry.close()


if __name__ == "__main__":
    sys.exit(main())
