"""
Monday2Friday workspace: the live picture the screens read.

During the pilot the account tracker stays the source of truth: the workspace
re-reads it whenever the file changes, so people keep working in Excel while
they test. What the tracker cannot hold lives in a small pilot store (SQLite):
forecast freezes, movement notes, variations, Kayleigh's answers to the open
questions, and who owns which account.

Projects are identified by tab and name, never by row, because rows shift
whenever someone inserts one.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from m2f.tracker_import import STATUSES, TrackerImport, import_tracker, norm, summarise

ZERO = Decimal("0")
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STATUS_ORDER = list(STATUSES) + ["Unclassified"]
PROPOSED_LABELS = {"Invoiced": "Invoiced", "Confirmed": "PO received", "TBC": "Awaiting PO", "Risk": "At risk"}

PILOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS freeze (
    id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
    frozen_at TEXT NOT NULL, frozen_by TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS freeze_line (
    freeze_id INTEGER NOT NULL REFERENCES freeze(id), pid TEXT NOT NULL, project TEXT NOT NULL,
    account TEXT NOT NULL, period TEXT NOT NULL, amount TEXT NOT NULL, status TEXT,
    PRIMARY KEY (freeze_id, pid, period));
CREATE TABLE IF NOT EXISTS movement_note (
    freeze_id INTEGER NOT NULL, pid TEXT NOT NULL, reason TEXT, next_action TEXT, owner TEXT,
    updated_at TEXT NOT NULL, updated_by TEXT, PRIMARY KEY (freeze_id, pid));
CREATE TABLE IF NOT EXISTS variation (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, project TEXT, account TEXT, title TEXT NOT NULL,
    sell_value TEXT, margin_pct TEXT, cpa_impact TEXT, approval_status TEXT NOT NULL DEFAULT 'To price',
    po_ref TEXT, owner TEXT, next_action TEXT, due_date TEXT,
    created_at TEXT NOT NULL, created_by TEXT, updated_at TEXT NOT NULL, updated_by TEXT);
CREATE TABLE IF NOT EXISTS decision (
    question_id TEXT PRIMARY KEY, choice TEXT, answer TEXT, decided_by TEXT, decided_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignment (
    kind TEXT NOT NULL, subject TEXT NOT NULL, person TEXT NOT NULL,
    updated_at TEXT NOT NULL, updated_by TEXT, PRIMARY KEY (kind, subject));
"""
VARIATION_STATUSES = ("To price", "Awaiting PO", "Decision needed", "Approved", "Rejected")
VARIATION_FIELDS = ("pid", "title", "sell_value", "margin_pct", "cpa_impact", "approval_status",
                    "po_ref", "owner", "next_action", "due_date")
ASSIGNMENT_KINDS = ("account_am", "project_am", "alias", "deputy")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def month_label(period: str) -> str:
    y, m = period.split("-")
    return f"{MONTH_NAMES[int(m) - 1]} {y}"


def add_months(period: str, n: int) -> str:
    y, m = (int(x) for x in period.split("-"))
    total = y * 12 + (m - 1) + n
    return f"{total // 12}-{total % 12 + 1:02d}"


def money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")[:80] or "unnamed"


class PilotStore:
    """SQLite file holding what the tracker can't: freezes, notes, variations, answers, owners."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(PILOT_SCHEMA)

    def query(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def write(self, sql, params=(), many=False):
        with self._lock, self._db:
            cur = self._db.executemany(sql, params) if many else self._db.execute(sql, params)
            return cur.lastrowid


class Workspace:
    def __init__(self, tracker_path: str | Path | None, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.tracker_path = Path(tracker_path) if tracker_path else None
        self.store = PilotStore(self.data_dir / "m2f_pilot.sqlite")
        self._lock = threading.Lock()
        self._mtime = None
        self.result: TrackerImport | None = None
        self.loaded_at: str | None = None
        self.error: str | None = None
        self.projects: dict[str, dict] = {}
        self.lines: list[dict] = []

    # ── Loading the tracker ─────────────────────────────────────────────────
    def uploaded_path(self) -> Path:
        return self.data_dir / "uploaded_tracker.xlsx"

    def source_path(self) -> Path | None:
        """The configured tracker, or the most recently uploaded copy if newer."""
        candidates = [p for p in (self.tracker_path, self.uploaded_path()) if p and p.exists()]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    def refresh(self, force: bool = False) -> None:
        path = self.source_path()
        if path is None:
            self.error = "No tracker yet: set M2F_TRACKER_PATH or load one from Settings."
            return
        mtime = path.stat().st_mtime
        with self._lock:
            if not force and self.result is not None and (path, mtime) == self._mtime:
                return
            try:
                result = import_tracker(path)
            except Exception as exc:  # noqa: BLE001 - shown on the status panel
                self.error = f"Could not read {path.name}: {exc}"
                return
            self._index(result)
            self.result, self._mtime, self.loaded_at, self.error = result, (path, mtime), now(), None

    def save_upload(self, data: bytes) -> None:
        if not data.startswith(b"PK"):
            raise ValueError("That file is not an .xlsx workbook.")
        self.uploaded_path().parent.mkdir(parents=True, exist_ok=True)
        self.uploaded_path().write_bytes(data)
        self.refresh(force=True)

    def _index(self, result: TrackerImport) -> None:
        parents = {a["name"]: a["parent"] for a in result.accounts}
        seen: Counter = Counter()
        by_key, projects = {}, {}
        for p in result.projects:
            base = f"{p.review_key.split('-')[0]}:{slug(p.name)}"
            seen[base] += 1
            pid = base if seen[base] == 1 else f"{base}~{seen[base]}"
            by_key[(p.tab, p.review_key)] = pid
            f = p.fields
            projects[pid] = {
                "pid": pid, "key": p.review_key, "tab": p.tab.strip(), "row": p.row, "hidden": p.hidden,
                "segment": p.segment, "account": p.account, "parent": parents.get(p.account),
                "name": p.name, "pm_raw": f.get("pm"), "am_raw": f.get("am"),
                "stage": f.get("stage_text"), "next_step": f.get("next_step"), "contact": f.get("contact"),
                "po_ref": f.get("po_ref"), "sales_order": f.get("sales_order"),
                "project_code": f.get("project_code"), "sell_value": f.get("sell_value"),
                "am_todo": f.get("am_todo"), "client_todo": f.get("client_todo"),
                "fields": f, "extra": p.extra,
            }
        self.projects = projects
        self.lines = [{
            "pid": by_key[(x.tab, x.review_key)], "period": x.period, "cell": x.cell, "status": x.status,
            "amount": Decimal(x.amount) if x.amount is not None else None, "raw": x.raw, "fill": x.fill,
        } for x in result.forecast_lines]
        self.issue_count = Counter(by_key.get((i.tab, i.review_key)) for i in result.issues if i.review_key)

    def ready(self) -> bool:
        self.refresh()
        return self.result is not None

    # ── People and ownership ────────────────────────────────────────────────
    def assignments(self) -> dict[str, dict[str, str]]:
        out = {k: {} for k in ASSIGNMENT_KINDS}
        for row in self.store.query("SELECT kind, subject, person FROM assignment"):
            out.setdefault(row["kind"], {})[row["subject"]] = row["person"]
        return out

    def set_assignment(self, kind: str, subject: str, person: str | None, by: str | None) -> None:
        if kind not in ASSIGNMENT_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ASSIGNMENT_KINDS)}")
        if person:
            self.store.write("INSERT INTO assignment (kind, subject, person, updated_at, updated_by) "
                             "VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, subject) DO UPDATE SET "
                             "person = excluded.person, updated_at = excluded.updated_at, "
                             "updated_by = excluded.updated_by", (kind, subject, person.strip(), now(), by))
        else:
            self.store.write("DELETE FROM assignment WHERE kind = ? AND subject = ?", (kind, subject))

    def _person(self, raw: str, aliases: dict) -> str:
        return aliases.get(norm(raw), raw.strip().title() if raw.strip().islower() else raw.strip())

    def pms_of(self, project: dict, aliases: dict) -> list[str]:
        raw = project.get("pm_raw")
        if not raw:
            return []
        names = [n for n in re.split(r"\s*(?:/|&|,|\band\b)\s*", str(raw)) if n.strip()]
        return [self._person(n, aliases) for n in names if norm(n) not in {"tbc", "na", "n/a"}]

    def am_of(self, project: dict, a: dict) -> str | None:
        if project["pid"] in a["project_am"]:
            return a["project_am"][project["pid"]]
        for account in (project["account"], project.get("parent")):
            if account and account in a["account_am"]:
                return a["account_am"][account]
        raw = project.get("am_raw")
        return self._person(str(raw), a["alias"]) if raw and norm(str(raw)) not in {"tbc", "na"} else None

    def project_rows(self, include_hidden: bool = True) -> list[dict]:
        a = self.assignments()
        totals = defaultdict(Decimal)
        for line in self.lines:
            if line["amount"] is not None:
                totals[line["pid"]] += line["amount"]
        rows = []
        for p in self.projects.values():
            if p["hidden"] and not include_hidden:
                continue
            rows.append({**{k: v for k, v in p.items() if k not in ("fields", "extra")},
                         "pms": self.pms_of(p, a["alias"]), "am": self.am_of(p, a),
                         "forecast_total": money(totals[p["pid"]]), "issues": self.issue_count.get(p["pid"], 0)})
        return rows

    def people(self) -> list[dict]:
        a = self.assignments()
        found: dict[str, dict] = {}
        for p in self.project_rows():
            for name in p["pms"]:
                found.setdefault(name, {"name": name, "pm_projects": 0, "am_projects": 0})["pm_projects"] += 1
            if p["am"]:
                found.setdefault(p["am"], {"name": p["am"], "pm_projects": 0, "am_projects": 0})["am_projects"] += 1
        for kind in ("account_am", "deputy"):
            for person in a[kind].values():
                found.setdefault(person, {"name": person, "pm_projects": 0, "am_projects": 0})
        for person in found.values():
            person["deputy"] = a["deputy"].get(person["name"])
            person["accounts"] = sorted(acc for acc, am in a["account_am"].items() if am == person["name"])
        return sorted(found.values(), key=lambda x: x["name"].lower())

    # ── Status labels follow Kayleigh's answer on the status mapping ─────────
    def status_labels(self) -> dict[str, str]:
        d = self.decisions_recorded().get("status_mapping")
        labels = dict(PROPOSED_LABELS) if d and d.get("choice") == "yes" else {s: s for s in STATUSES}
        labels["Unclassified"] = "Unclassified"
        return labels

    # ── Forecast figures ────────────────────────────────────────────────────
    def _bucket(self, lines) -> dict:
        by_status = {s: ZERO for s in STATUS_ORDER}
        for line in lines:
            if line["amount"] is not None:
                by_status[line["status"] or "Unclassified"] += line["amount"]
        return {"total": money(sum(by_status.values(), ZERO)),
                "by_status": {s: money(v) for s, v in by_status.items()}}

    def periods(self, asof: str | None) -> dict:
        this = asof or date.today().strftime("%Y-%m")
        nxt = add_months(this, 1)
        year = this[:4]
        return {"this": this, "next": nxt, "year": year, "this_label": month_label(this),
                "next_label": month_label(nxt), "year_label": f"FY{year[2:]}"}

    def cards(self, lines: list[dict], per: dict) -> dict:
        return {
            "this_month": {"label": per["this_label"], **self._bucket(l for l in lines if l["period"] == per["this"])},
            "next_month": {"label": per["next_label"], **self._bucket(l for l in lines if l["period"] == per["next"])},
            "full_year": {"label": per["year_label"],
                          **self._bucket(l for l in lines if (l["period"] or "")[:4] == per["year"])},
        }

    def by_account(self, lines: list[dict], per: dict) -> list[dict]:
        rows: dict[str, dict] = {}
        for line in lines:
            if line["amount"] is None:
                continue
            p = self.projects[line["pid"]]
            row = rows.setdefault(p["account"], {"account": p["account"], "parent": p["parent"],
                                                 "this": ZERO, "next": ZERO, "year": ZERO})
            if line["period"] == per["this"]:
                row["this"] += line["amount"]
            if line["period"] == per["next"]:
                row["next"] += line["amount"]
            if (line["period"] or "")[:4] == per["year"]:
                row["year"] += line["amount"]
        out = [{**r, "this": money(r["this"]), "next": money(r["next"]), "year": money(r["year"])}
               for r in rows.values() if r["this"] or r["next"] or r["year"]]
        return sorted(out, key=lambda r: (r["parent"] or r["account"], r["parent"] is not None, -Decimal(r["year"])))

    def at_risk(self, lines: list[dict], per: dict, limit: int = 12) -> list[dict]:
        a = self.assignments()
        risk = defaultdict(lambda: defaultdict(Decimal))
        for line in lines:
            if line["status"] == "Risk" and line["amount"] and line["period"] in (per["this"], per["next"]):
                risk[line["pid"]][line["period"]] += line["amount"]
        out = []
        for pid, by_period in risk.items():
            p = self.projects[pid]
            out.append({"pid": pid, "project": p["name"], "account": p["account"],
                        "amount": money(sum(by_period.values(), ZERO)),
                        "months": [month_label(m) for m in sorted(by_period)],
                        "next_step": p["next_step"], "pms": self.pms_of(p, a["alias"]), "am": self.am_of(p, a)})
        return sorted(out, key=lambda r: -Decimal(r["amount"]))[:limit]

    def dashboard(self, asof: str | None = None) -> dict:
        per = self.periods(asof)
        return {"periods": per, "labels": self.status_labels(), "cards": self.cards(self.lines, per),
                "accounts": self.by_account(self.lines, per), "needs_decision": self.at_risk(self.lines, per),
                "latest_freeze": self.latest_freeze()}

    def _lines_for(self, pids: set[str]) -> list[dict]:
        return [l for l in self.lines if l["pid"] in pids]

    def am_workspace(self, name: str, asof: str | None = None) -> dict:
        per = self.periods(asof)
        mine = [p for p in self.project_rows() if p["am"] == name]
        pids = {p["pid"] for p in mine}
        lines = self._lines_for(pids)
        freeze = self.latest_freeze()
        moved = [m for m in self.review(freeze["id"], asof)["movements"] if m["pid"] in pids] if freeze else []
        live = sorted((p for p in mine if not p["hidden"]), key=lambda p: p["name"].lower())
        return {"person": name, "periods": per, "labels": self.status_labels(), "cards": self.cards(lines, per),
                "moved": moved, "projects": live, "hidden_projects": len(mine) - len(live),
                "needs_decision": self.at_risk(lines, per), "accounts": self.assignments_for(name)}

    def assignments_for(self, name: str) -> list[str]:
        return sorted(acc for acc, am in self.assignments()["account_am"].items() if am == name)

    def pm_overview(self, name: str, asof: str | None = None) -> dict:
        per = self.periods(asof)
        mine = [p for p in self.project_rows() if name in p["pms"]]
        live = [p for p in mine if not p["hidden"]]
        due = {l["pid"] for l in self._lines_for({p["pid"] for p in live})
               if l["period"] in (per["this"], per["next"]) and l["amount"]}
        risk = {r["pid"] for r in self.at_risk(self._lines_for({p["pid"] for p in live}), per, limit=999)}
        for p in live:
            p["billing_soon"] = p["pid"] in due
            p["at_risk"] = p["pid"] in risk
        live.sort(key=lambda p: (not p["at_risk"], not p["billing_soon"], p["name"].lower()))
        return {"person": name, "periods": per, "projects": live, "hidden_projects": len(mine) - len(live),
                "counts": {"live": len(live), "at_risk": len(risk), "billing_soon": len(due),
                           "no_next_step": sum(1 for p in live if not p["next_step"])}}

    def project_detail(self, pid: str) -> dict | None:
        p = self.projects.get(pid)
        if not p:
            return None
        a = self.assignments()
        lines = sorted((l for l in self.lines if l["pid"] == pid), key=lambda l: l["period"] or "")
        issues = [vars(i) for i in self.result.issues if i.review_key == p["key"] and i.tab.strip() == p["tab"]]
        variations = self.store.query("SELECT * FROM variation WHERE pid = ? ORDER BY id DESC", (pid,))
        return {**p, "pms": self.pms_of(p, a["alias"]), "am": self.am_of(p, a),
                "lines": [{**l, "amount": money(l["amount"]) if l["amount"] is not None else None,
                           "period_label": month_label(l["period"]) if l["period"] else None} for l in lines],
                "issues": issues, "variations": variations}

    def accounts(self, asof: str | None = None) -> dict:
        per = self.periods(asof)
        a = self.assignments()
        rows = self.by_account(self.lines, per)
        counts = Counter(p["account"] for p in self.projects.values() if not p["hidden"])
        for r in rows:
            r["owner"] = a["account_am"].get(r["account"]) or (a["account_am"].get(r["parent"]) if r["parent"] else None)
            r["live_projects"] = counts.get(r["account"], 0)
        known = {r["account"] for r in rows}
        for acc in self.result.accounts:
            if acc["name"] not in known:
                rows.append({"account": acc["name"], "parent": acc["parent"], "this": "0.00", "next": "0.00",
                             "year": "0.00", "owner": a["account_am"].get(acc["name"]),
                             "live_projects": counts.get(acc["name"], 0)})
        return {"periods": per, "accounts": rows, "brands": self.result.brands}

    # ── Forecast freeze and the weekly review ───────────────────────────────
    def freeze(self, label: str, by: str | None) -> dict:
        source = self.source_path().name if self.source_path() else None
        fid = self.store.write("INSERT INTO freeze (label, frozen_at, frozen_by, source) VALUES (?, ?, ?, ?)",
                               (label.strip() or f"Freeze {date.today():%d %b %Y}", now(), by, source))
        grouped = defaultdict(lambda: [ZERO, None])
        for line in self.lines:
            if line["amount"] is None or not line["period"]:
                continue
            g = grouped[(line["pid"], line["period"])]
            g[0] += line["amount"]
            g[1] = line["status"]
        self.store.write(
            "INSERT INTO freeze_line (freeze_id, pid, project, account, period, amount, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(fid, pid, self.projects[pid]["name"], self.projects[pid]["account"], period, money(v[0]), v[1])
             for (pid, period), v in grouped.items()], many=True)
        return self.store.query("SELECT * FROM freeze WHERE id = ?", (fid,))[0]

    def freezes(self) -> list[dict]:
        return self.store.query("SELECT f.*, COUNT(l.pid) AS lines FROM freeze f "
                                "LEFT JOIN freeze_line l ON l.freeze_id = f.id GROUP BY f.id ORDER BY f.id DESC")

    def latest_freeze(self) -> dict | None:
        rows = self.store.query("SELECT * FROM freeze ORDER BY id DESC LIMIT 1")
        return rows[0] if rows else None

    def review(self, freeze_id: int, asof: str | None = None) -> dict:
        per = self.periods(asof)
        frozen = self.store.query("SELECT * FROM freeze_line WHERE freeze_id = ?", (freeze_id,))
        before = defaultdict(dict)
        names = {}
        for row in frozen:
            before[row["pid"]][row["period"]] = (Decimal(row["amount"]), row["status"])
            names[row["pid"]] = (row["project"], row["account"])
        after = defaultdict(dict)
        for line in self.lines:
            if line["amount"] is None or not line["period"]:
                continue
            amt, _ = after[line["pid"]].get(line["period"], (ZERO, None))
            after[line["pid"]][line["period"]] = (amt + line["amount"], line["status"])
        notes = {n["pid"]: n for n in self.store.query("SELECT * FROM movement_note WHERE freeze_id = ?", (freeze_id,))}
        a = self.assignments()
        movements = []
        for pid in set(before) | set(after):
            changes = []
            for period in sorted(set(before[pid]) | set(after[pid])):
                b_amt, b_st = before[pid].get(period, (ZERO, None))
                a_amt, a_st = after[pid].get(period, (ZERO, None))
                if b_amt != a_amt or (b_st != a_st and b_amt and a_amt):
                    changes.append({"period": period, "label": month_label(period), "before": money(b_amt),
                                    "after": money(a_amt), "status_before": b_st, "status_after": a_st})
            if not changes:
                continue
            p = self.projects.get(pid)
            project, account = (p["name"], p["account"]) if p else names[pid]
            net = sum((Decimal(c["after"]) - Decimal(c["before"]) for c in changes), ZERO)
            movements.append({
                "pid": pid, "project": project, "account": account, "changes": changes, "net": money(net),
                "summary": describe(changes), "removed_from_tracker": p is None,
                "am": self.am_of(p, a) if p else None, "pms": self.pms_of(p, a["alias"]) if p else [],
                "reason": notes.get(pid, {}).get("reason"), "next_action": notes.get(pid, {}).get("next_action"),
                "owner": notes.get(pid, {}).get("owner"),
            })
        movements.sort(key=lambda m: -max(abs(Decimal(c["after"]) - Decimal(c["before"])) for c in m["changes"]))

        def total(source, period_test):
            return money(sum((amt for by in source.values() for period, (amt, _) in by.items() if period_test(period)), ZERO))

        compare = {}
        for key, test, label in (("this_month", lambda x: x == per["this"], per["this_label"]),
                                 ("next_month", lambda x: x == per["next"], per["next_label"]),
                                 ("full_year", lambda x: x[:4] == per["year"], per["year_label"])):
            b, now_ = total(before, test), total(after, test)
            compare[key] = {"label": label, "at_freeze": b, "now": now_, "change": money(Decimal(now_) - Decimal(b))}
        freeze = self.store.query("SELECT * FROM freeze WHERE id = ?", (freeze_id,))
        return {"freeze": freeze[0] if freeze else None, "periods": per, "compare": compare, "movements": movements,
                "variations": self.variations(open_only=True)}

    def save_note(self, freeze_id: int, pid: str, reason, next_action, owner, by) -> None:
        self.store.write(
            "INSERT INTO movement_note (freeze_id, pid, reason, next_action, owner, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(freeze_id, pid) DO UPDATE SET reason = excluded.reason, "
            "next_action = excluded.next_action, owner = excluded.owner, updated_at = excluded.updated_at, "
            "updated_by = excluded.updated_by", (freeze_id, pid, reason, next_action, owner, now(), by))

    # ── Variations ──────────────────────────────────────────────────────────
    def variations(self, open_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM variation"
        if open_only:
            sql += " WHERE approval_status NOT IN ('Approved', 'Rejected')"
        return self.store.query(sql + " ORDER BY id DESC")

    def save_variation(self, data: dict, by: str | None, vid: int | None = None) -> dict:
        clean = {k: (str(data[k]).strip() if data.get(k) not in (None, "") else None)
                 for k in VARIATION_FIELDS if k in data}
        if clean.get("approval_status") and clean["approval_status"] not in VARIATION_STATUSES:
            raise ValueError(f"approval_status must be one of {', '.join(VARIATION_STATUSES)}")
        if "pid" in clean:
            p = self.projects.get(clean["pid"] or "")
            if clean["pid"] and not p:
                raise ValueError("Unknown project")
            clean["project"], clean["account"] = (p["name"], p["account"]) if p else (None, None)
        if vid is None:
            if not clean.get("title"):
                raise ValueError("A variation needs a title")
            clean.setdefault("approval_status", "To price")
            clean.update(created_at=now(), created_by=by, updated_at=now(), updated_by=by)
            cols = ", ".join(clean)
            vid = self.store.write(f"INSERT INTO variation ({cols}) VALUES ({', '.join('?' * len(clean))})",
                                   tuple(clean.values()))
        else:
            if not self.store.query("SELECT id FROM variation WHERE id = ?", (vid,)):
                raise KeyError(vid)
            clean.update(updated_at=now(), updated_by=by)
            sets = ", ".join(f"{k} = ?" for k in clean)
            self.store.write(f"UPDATE variation SET {sets} WHERE id = ?", (*clean.values(), vid))
        return self.store.query("SELECT * FROM variation WHERE id = ?", (vid,))[0]

    # ── Open questions for Kayleigh ─────────────────────────────────────────
    def decisions_recorded(self) -> dict:
        return {d["question_id"]: d for d in self.store.query("SELECT * FROM decision")}

    def record_decision(self, qid: str, choice: str | None, answer: str | None, by: str | None) -> None:
        if qid not in {q["id"] for q in QUESTIONS}:
            raise KeyError(qid)
        self.store.write("INSERT INTO decision (question_id, choice, answer, decided_by, decided_at) VALUES "
                         "(?, ?, ?, ?, ?) ON CONFLICT(question_id) DO UPDATE SET choice = excluded.choice, "
                         "answer = excluded.answer, decided_by = excluded.decided_by, decided_at = excluded.decided_at",
                         (qid, choice, answer, by, now()))

    def questions(self) -> list[dict]:
        recorded = self.decisions_recorded()
        evidence = self._evidence()
        return [{**q, "evidence": evidence.get(q["id"], []), "decision": recorded.get(q["id"])} for q in QUESTIONS]

    def _evidence(self) -> dict[str, list[str]]:
        r = self.result
        issues = defaultdict(list)
        for i in r.issues:
            issues[i.code].append(i)
        by_status = defaultdict(Decimal)
        for line in self.lines:
            if line["amount"] is not None:
                by_status[line["status"] or "Unclassified"] += line["amount"]
        hidden = [p for p in self.projects.values() if p["hidden"]]
        hidden_value = sum((l["amount"] for l in self.lines if l["amount"] and self.projects[l["pid"]]["hidden"]), ZERO)
        with_am = sum(1 for p in self.projects.values() if p["am_raw"])
        people = {p["key"]: p for p in r.people}
        unclassified = defaultdict(lambda: [0, ZERO, set()])
        for line in self.lines:
            if line["status"] is None and line["amount"] is not None:
                u = unclassified[line["fill"]]
                u[0] += 1
                u[1] += line["amount"]
                u[2].add(self.projects[line["pid"]]["tab"])
        return {
            "status_mapping": [f"{s}: £{by_status[s]:,.2f}" for s in STATUS_ORDER if by_status.get(s)],
            "hidden_rows": [f"{len(hidden)} of {len(self.projects)} projects are hidden in the tracker.",
                            f"They carry £{hidden_value:,.2f} of forecast across all months."],
            "am_ownership": [f"Only {with_am} of {len(self.projects)} projects name an AM."]
                            + [f"'{k.upper()}' appears as {', '.join(v['roles'])} on {v['projects']} projects."
                               for k, v in people.items() if len(k) <= 3],
            "chloe": [f"'{p['key'].title()}' is named as {', '.join(p['roles'])} on {p['projects']} projects."
                      for p in r.people if p["key"].startswith("chloe")],
            "fy27_budget": [i.message for i in issues["account_total_misses_months"]],
            "outside_totals": [i.message for i in issues["value_outside_total"]],
            "numeric_names": [i.message for i in issues["name_is_number"]],
            "unclassified_colours": [f"#{fill}: {n} cells, £{amt:,.2f} ({', '.join(sorted(tabs))})"
                                     for fill, (n, amt, tabs) in sorted(unclassified.items(), key=lambda kv: -kv[1][1])],
            "unreadable_amounts": [f"{i.tab.strip()} {i.cell}: {i.message}" for i in issues["amount_unreadable"]]
                                  + [f"{i.tab.strip()} {i.cell}: {i.message}" for i in issues["amount_typed_as_text"]],
            "sub_accounts": [f"{len(issues['sub_account_unconfirmed'])} Boots rows sit outside the BUK and Sigma ranges: "
                             + ", ".join(i.cell for i in issues["sub_account_unconfirmed"])] if issues["sub_account_unconfirmed"] else [],
        }

    # ── Status for the settings panel ───────────────────────────────────────
    def status(self) -> dict:
        self.refresh()
        path = self.source_path()
        return {
            "ready": self.result is not None, "error": self.error, "loaded_at": self.loaded_at,
            "source": path.name if path else None,
            "source_kind": None if not path else ("uploaded" if path == self.uploaded_path() else "configured"),
            "source_modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds") if path else None,
            "summary": summarise(self.result) if self.result else None,
            "reconciliation": self.result.reconciliation if self.result else [],
            "store": str(self.store.path), "freezes": len(self.freezes()),
            "variations": len(self.variations()), "decisions": len(self.decisions_recorded()),
        }


def describe(changes: list[dict]) -> str:
    """Plain words for one project's movement since the freeze."""
    deltas = [(c, Decimal(c["after"]) - Decimal(c["before"])) for c in changes]
    moved = [(c, d) for c, d in deltas if d]
    if len(moved) == 2 and moved[0][1] == -moved[1][1]:
        src, dst = (moved[0], moved[1]) if moved[0][1] < 0 else (moved[1], moved[0])
        return f"£{abs(src[1]):,.0f} moved from {src[0]['label']} to {dst[0]['label']}"
    parts = []
    for c, d in deltas:
        if d and Decimal(c["before"]) == 0:
            parts.append(f"£{d:,.0f} added in {c['label']}")
        elif d and Decimal(c["after"]) == 0:
            parts.append(f"£{-d:,.0f} removed from {c['label']}")
        elif d:
            parts.append(f"{c['label']} {'up' if d > 0 else 'down'} £{abs(d):,.0f}")
        elif c["status_before"] != c["status_after"]:
            parts.append(f"{c['label']} {c['status_before'] or 'Unclassified'} to {c['status_after'] or 'Unclassified'}")
    return "; ".join(parts)


QUESTIONS = [
    {"id": "status_mapping", "topic": "Forecast status",
     "question": "Does Confirmed mean PO received, and TBC mean Awaiting PO?",
     "why": "Your dashboards split each month into Invoiced, PO received, Awaiting PO and At risk. "
            "The tracker's colours say Invoiced, Confirmed, TBC and Risk.",
     "choices": ["yes", "no"]},
    {"id": "unclassified_colours", "topic": "Forecast status",
     "question": "What do the colours that aren't on the legend mean?",
     "why": "These forecast cells have a colour the tab's legend doesn't list, so they count as Unclassified."},
    {"id": "hidden_rows", "topic": "Projects",
     "question": "Which hidden rows are archive, and which are still live?",
     "why": "Hidden rows still count in the tracker's totals. Live projects appear in the AM and PM workspaces."},
    {"id": "am_ownership", "topic": "People",
     "question": "Who owns each account, and who are the initials in the PM and AM columns?",
     "why": "The AM workspace, morning brief, capacity and cover all start from who owns what. "
            "Owners can be set in Settings once agreed."},
    {"id": "chloe", "topic": "People",
     "question": "Is the Chloe in the PM column the Beauty AM, or a different person?",
     "why": "One name in two roles changes both the PM overview and the AM workspace."},
    {"id": "fy27_budget", "topic": "Budget",
     "question": "Which FY27 budget is right: the monthly plan on the Forcasting Total sheet, or the split by account?",
     "why": "The dashboard compares forecast with budget, and the tracker's FY27 account totals don't add up."},
    {"id": "outside_totals", "topic": "Totals",
     "question": "Should these values count? They sit outside the range their tab's total adds up.",
     "why": "Including or excluding them changes the monthly totals."},
    {"id": "numeric_names", "topic": "Projects",
     "question": "What should the Sigma lines be called? They are named only by an order number.",
     "why": "People need to recognise a project on the boards and in their morning brief."},
    {"id": "sub_accounts", "topic": "Accounts",
     "question": "Are these Boots rows Boots UK or Sigma?",
     "why": "They sit outside the row ranges the totals sheet uses for each."},
    {"id": "unreadable_amounts", "topic": "Totals",
     "question": "What are these amounts meant to be?",
     "why": "They are typed as text, so either the tracker's totals leave them out or they can't be read at all."},
    {"id": "credit_limits", "topic": "Accounts",
     "question": "Can credit limits come live from Sage X3 instead of being copied across?",
     "why": "They'd stay current, and only people with access to Sage would see them.", "choices": ["yes", "no"]},
]
