"""SameDay's picture index, kept current from K: once a day, with a daily email.

5 November 2026 (James): "e-mail me every day with any changes to [the index on K:] ... if it's updated we copy auto
with the daily check to the server ... just what we've copied over today, only the index." Only the picture index and
its job list are brought across - the thumbnails stay on K:. These run offline: K: and the server are temporary
folders, SameDay and its service are stand-ins.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
import sameday_index as SI  # noqa: E402
import sameday_watch as W  # noqa: E402

OLD = "Index built:   2026-11-04 21:56 | Pictures: 5"
NEW = "Index built:   2026-11-11 21:56 | Pictures: 6"


def make_build(folder: Path, pictures: int, rows: int, build: str, old: bool = True):
    """An index (emb.npy's header is all that is read), a job list and BUILD.txt, as Muhammad's update writes them."""
    folder.mkdir(parents=True, exist_ok=True)
    head = "{'descr': '<f4', 'fortran_order': False, 'shape': (%d, 512), }" % pictures
    with zipfile.ZipFile(folder / "all_img_index.npz", "w") as z:
        z.writestr("emb.npy", b"\x93NUMPY\x01\x00" + head.encode().ljust(118) + b"\n" + b"\0" * 64)
    (folder / "projects.db").unlink(missing_ok=True)         # this week's build replaces last week's
    con = sqlite3.connect(folder / "projects.db")
    con.execute("CREATE TABLE project_images (img_id INTEGER PRIMARY KEY, job_no TEXT)")
    con.executemany("INSERT INTO project_images VALUES (?, ?)", [(i, "12148") for i in range(rows)])
    con.commit()
    con.close()
    (folder / "BUILD.txt").write_text(build.replace(" | ", "\n"), encoding="utf-8")
    if old:                                     # finished copying: not written to for a while
        for p in folder.iterdir():
            os.utime(p, (time.time() - 3600, time.time() - 3600))


class Server:
    """The server's SameDay folder, its service, and what SameDay says - stand-ins."""

    def __init__(self, root: Path, build: str = OLD, jobs_after: int = 12073):
        self.root = root
        (root / "brief_lite").mkdir(parents=True)
        make_build(root / "_k_then", 5, 5, build)
        (root / "_k_then" / "all_img_index.npz").replace(root / "all_img_index.npz")
        (root / "_k_then" / "projects.db").replace(root / "brief_lite" / "projects.db")
        (root / "all_img_index.BUILD.txt").write_text(build.replace(" | ", "\n"), encoding="utf-8")
        self.calls, self.jobs_after = [], jobs_after

    def sc(self, action, name="SDISameDay"):
        self.calls.append(action)

    def service(self, name):
        return "STOPPED"

    def get(self, url, headers=None, timeout=15, redirects=True):
        return 200, {"past_work": {"jobs": self.jobs_after, "pictures": bool(self.jobs_after), "why": "" if self.jobs_after
                                   else "job index: database disk image is malformed"}}, ""

    def refresh(self, k, free=100.0):
        return SI.refresh(self.root, k, get=self.get, service=self.service, sc=self.sc, free=lambda p: free,
                          settle_s=0, wait_s=2, poll_s=0.01, now=datetime(2026, 11, 12, 6, 0))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdindex-"))
        self.k = self.tmp / "k"
        self.server = Server(self.tmp / "server")

    def test_the_same_build_changes_nothing(self):
        make_build(self.k, 5, 5, OLD)
        rep = self.server.refresh(self.k)
        self.assertEqual(rep["action"], "none")
        self.assertEqual(self.server.calls, [])                       # SameDay never stopped

    def test_a_new_build_is_brought_across_and_switched_on(self):
        make_build(self.k, 6, 6, NEW)
        rep = self.server.refresh(self.k)
        self.assertEqual(rep["action"], "copied", rep)
        self.assertTrue(rep["pictures_on"])
        self.assertEqual(SI.pictures_in(self.server.root / "all_img_index.npz"), 6)
        self.assertEqual(SI.rows_in(self.server.root / "brief_lite" / "projects.db"), 6)
        self.assertIn("2026-11-11", SI.build_text(self.server.root / "all_img_index.BUILD.txt"))
        self.assertEqual(self.server.calls, ["stop", "start"])        # down for seconds, once
        kept = list((self.server.root / "backups").glob("before-index-auto-*"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(SI.rows_in(kept[0] / "projects.db"), 5)      # the old job list kept
        self.assertFalse(list(self.server.root.rglob("*.incoming")))

    def test_only_the_index_and_its_job_list_never_the_thumbnails(self):
        make_build(self.k, 6, 6, NEW)
        (self.k / "all_img_thumbs").mkdir()
        (self.k / "all_img_thumbs" / "1.jpg").write_bytes(b"x")
        self.server.refresh(self.k)
        self.assertFalse((self.server.root / "all_img_thumbs").exists())

    def test_a_job_list_from_another_build_is_refused(self):
        make_build(self.k, 6, 5, NEW)
        rep = self.server.refresh(self.k)
        self.assertEqual(rep["action"], "skipped")
        self.assertIn("doesn't match", rep["detail"])
        self.assertEqual(self.server.calls, [])
        self.assertEqual(SI.pictures_in(self.server.root / "all_img_index.npz"), 5)

    def test_a_build_still_arriving_waits_for_tomorrow(self):
        make_build(self.k, 6, 6, NEW, old=False)
        self.assertEqual(self.server.refresh(self.k)["action"], "waiting")
        self.assertEqual(self.server.calls, [])

    def test_never_when_the_server_s_c_would_be_left_short(self):
        make_build(self.k, 6, 6, NEW)
        rep = self.server.refresh(self.k, free=19.5)                 # under the 20 GB that must stay free
        self.assertEqual(rep["action"], "skipped")
        self.assertIn("20 GB kept free", rep["detail"])
        rep = SI.refresh(self.server.root, self.k, get=self.server.get, service=self.server.service, sc=self.server.sc,
                         free=lambda p: None, settle_s=0, wait_s=1, poll_s=0.01)
        self.assertEqual(rep["action"], "skipped")                    # free space unknown: no copy
        self.assertEqual(self.server.calls, [])

    def test_a_job_list_sameday_cant_read_is_put_straight_back(self):
        make_build(self.k, 6, 6, NEW)
        self.server.jobs_after = 0
        rep = self.server.refresh(self.k)
        self.assertEqual(rep["action"], "failed")
        self.assertIn("put back", rep["detail"])
        self.assertEqual(SI.rows_in(self.server.root / "brief_lite" / "projects.db"), 5)
        self.assertIn("2026-11-04", SI.build_text(self.server.root / "all_img_index.BUILD.txt"))

    def test_no_build_txt_no_copy(self):
        make_build(self.k, 6, 6, NEW)
        (self.k / "BUILD.txt").unlink()
        self.assertEqual(self.server.refresh(self.k)["action"], "skipped")

    def test_only_the_newest_automatic_backups_are_kept(self):
        for i, n in enumerate((6, 7, 8)):
            make_build(self.k, n, n, f"Index built: 2026-11-{11 + i}")
            SI.refresh(self.server.root, self.k, get=self.server.get, service=self.server.service, sc=self.server.sc,
                       free=lambda p: 100.0, settle_s=0, wait_s=1, poll_s=0.01, now=datetime(2026, 11, 12 + i, 6, 0))
        self.assertEqual(len(list((self.server.root / "backups").glob("before-index-auto-*"))), 2)


class DailyEmailTests(unittest.TestCase):
    NOW = datetime(2026, 11, 12, 7, 0)

    def test_what_it_says(self):
        rep = {"action": "none", "detail": "", "k_build": OLD, "server_build": OLD, "all_img_index.npz": "496 MB",
               "projects.db": "78 MB", "pictures_on": None, "jobs": None}
        mail = SI.compose(rep, 417_900, 417_787, self.NOW)
        self.assertEqual(mail["subject"], "SDI Live index: no change")
        self.assertIn("Thumbnails on K:: 417,900 (+113 since yesterday)", mail["text"])
        self.assertIn("On the server: " + OLD, mail["text"])
        copied = SI.compose(dict(rep, action="copied", detail="picture matching is on", jobs=12090, pictures_on=True),
                            None, None, self.NOW)
        self.assertEqual(copied["subject"], "SDI Live index: new build copied to the server")
        self.assertIn("12090 past jobs, picture matching on", copied["text"])
        self.assertEqual(SI.compose(dict(rep, action="skipped", detail="x"), None, None, self.NOW)["subject"],
                         "SDI Live index: new build NOT copied")

    def test_the_watch_does_it_once_a_day_and_emails_once(self):
        d = Path(tempfile.mkdtemp(prefix="daily-"))
        keep = (W.STATE, W.check, W.send, W.datetime)
        env = {k: os.environ.get(k) for k in ("SAMEDAY_ALERT_TO", "SAMEDAY_DAILY_TO", "SAMEDAY_INDEX_FROM", "SAMEDAY_DIR")}
        refreshed, sent, backed_up, mails = [], [], [], []
        keep_refresh, keep_count = SI.refresh, SI.count_thumbs
        import sameday_backup as B
        keep_backup, keep_compose = B.backup, SI.compose
        B.backup = lambda *a, **k: backed_up.append(k.get("now")) or {
            "status": "ok", "detail": "", "when": k["now"].isoformat(timespec="minutes"), "free_gb": 512.0,
            "files_copied": 3, "files_mb": 1.0, "databases": {"lite.db": {"ok": True, "sessions": 5, "messages": 40}}}
        SI.compose = lambda *a, **k: mails.append(k.get("backup")) or keep_compose(*a, **k)
        clock = [datetime(2026, 11, 12, 5, 30)]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]
        W.STATE, W.datetime = d / "state.json", Clock
        W.check = lambda log_text="": ([], {})
        W.send = lambda to, email: sent.append((to, email["subject"])) or {"sent": True}
        SI.refresh = lambda *a, **k: refreshed.append(1) or {"action": "none", "detail": "", "k_build": OLD,
                                                             "server_build": OLD, "pictures_on": None, "jobs": None}
        SI.count_thumbs = lambda folder, limit_s=300: 417_787
        os.environ.update(SAMEDAY_ALERT_TO="james@example.com,mo@example.com", SAMEDAY_DAILY_TO="james@example.com",
                          SAMEDAY_INDEX_FROM=str(d / "k"), SAMEDAY_DIR=str(d / "server"))
        try:
            W.main(["--send"])                       # 05:30 - before the daily hour: nothing (the backup ran from 1am)
            self.assertEqual((refreshed, sent), ([], []))
            self.assertEqual(len(backed_up), 1)
            clock[0] = datetime(2026, 11, 12, 6, 0)
            W.main(["--send"])                       # 06:00 - checked and copied if new, but no email at 6am
            self.assertEqual((len(refreshed), sent), (1, []))
            clock[0] = datetime(2026, 11, 12, 7, 0)
            W.main(["--send"])                       # 07:00 - the email, to James only
            self.assertEqual(sent, [(["james@example.com"], "SDI Live index: no change")])
            clock[0] = datetime(2026, 11, 12, 7, 15)
            W.main(["--send"])                       # and not again today
            self.assertEqual((len(refreshed), len(sent)), (1, 1))
            self.assertEqual(json.loads((d / "state.json").read_text())["daily"]["thumbs"], 417_787)
            self.assertEqual(len(backed_up), 1)                         # once a night, not every 15 minutes
            self.assertIn("5 chats, 40 lines", mails[-1])                # and last night's backup is in the email
        finally:
            W.STATE, W.check, W.send, W.datetime = keep
            SI.refresh, SI.count_thumbs = keep_refresh, keep_count
            B.backup, SI.compose = keep_backup, keep_compose
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class OnTheServerTests(unittest.TestCase):
    def test_ship_it_carries_it(self):
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        self.assertIn('"sameday_index.py"', deploy.split("$Files = @(", 1)[1].split("\n)", 1)[0])


if __name__ == "__main__":
    unittest.main()
