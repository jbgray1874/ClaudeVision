"""SameDay's chats and work, backed up to the server's D: every night.

5 November 2026 (James: "yes, definitely need a back up"): the chats, briefs, Craft Memory and everything SameDay made
were on the server's C: alone. These run offline: SameDay's folder and D: are temporary folders.
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
import sameday_backup as B  # noqa: E402

NIGHT = datetime(2026, 11, 6, 1, 0)


def make_sameday(root: Path, chats: int = 3) -> Path:
    (root / "brief_lite" / "out" / "spaces" / "sp1").mkdir(parents=True)
    (root / "brief_lite" / "client_files" / "tesco").mkdir(parents=True)
    (root / "craft").mkdir()
    (root / "studio_data").mkdir()
    con = sqlite3.connect(root / "brief_lite" / "lite.db")
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, brief TEXT)")
    con.execute("CREATE TABLE messages (id TEXT, session TEXT, text TEXT)")
    con.executemany("INSERT INTO sessions VALUES (?, ?)", [(f"c{i}", "{}") for i in range(chats)])
    con.executemany("INSERT INTO messages VALUES (?, ?, ?)", [(f"m{i}", "c0", "budget about five thousand") for i in range(10)])
    con.commit()
    con.close()
    sqlite3.connect(root / "craft" / "craft.db").execute("CREATE TABLE notes (x)").connection.close()
    (root / "brief_lite" / "out" / "c0_render_A.png").write_bytes(b"png" * 100)
    (root / "brief_lite" / "out" / "c0_brief.pdf").write_bytes(b"%PDF" * 100)
    (root / "brief_lite" / "out" / "spaces" / "sp1" / "photo.jpg").write_bytes(b"jpg")
    (root / "brief_lite" / "client_files" / "tesco" / "brief.docx").write_bytes(b"doc")
    (root / "studio_data" / "ai_switch.json").write_text('{"brief_lite_daily_cap_usd": 20}', encoding="utf-8")
    (root / "brief_lite" / ".env").write_text("OPENAI_API_KEY=sk-not-real", encoding="utf-8")       # the keys
    (root / "studio_data" / ".env").write_text("X=1", encoding="utf-8")
    (root / "brief_lite" / "projects.db").write_bytes(b"from K:")                                  # not ours
    return root


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdbackup-"))
        self.sd = make_sameday(self.tmp / "SDI_Automation")
        self.to = self.tmp / "D" / "SameDayBackups"

    def run_backup(self, now=NIGHT, free=500.0, **k):
        return B.backup(self.sd, self.to, now=now, free=lambda p: free, **k)

    def test_the_chats_and_craft_memory_copied_and_checked(self):
        rep = self.run_backup()
        self.assertEqual(rep["status"], "ok", rep)
        night = self.to / "databases" / "2026-11-06"
        con = sqlite3.connect(night / "lite.db")
        self.assertEqual(con.execute("SELECT count(*) FROM sessions").fetchone()[0], 3)
        self.assertEqual(con.execute("SELECT count(*) FROM messages").fetchone()[0], 10)
        con.close()
        self.assertTrue((night / "craft.db").exists())
        self.assertEqual((rep["databases"]["lite.db"]["sessions"], rep["databases"]["lite.db"]["messages"]), (3, 10))
        self.assertFalse(list(self.to.rglob("*.part")))

    def test_safe_while_sameday_is_writing(self):
        live = sqlite3.connect(self.sd / "brief_lite" / "lite.db")      # SameDay has it open, mid-change
        live.execute("INSERT INTO sessions VALUES ('c9', '{}')")
        rep = self.run_backup()
        live.commit()
        live.close()
        self.assertEqual(rep["status"], "ok", rep)
        self.assertEqual(rep["databases"]["lite.db"]["sessions"], 3)  # the last saved state, whole

    def test_what_it_made_and_was_sent_never_the_keys_or_k(self):
        self.run_backup()
        files = self.to / "files"
        for rel in ("brief_lite/out/c0_render_A.png", "brief_lite/out/c0_brief.pdf", "brief_lite/out/spaces/sp1/photo.jpg",
                    "brief_lite/client_files/tesco/brief.docx", "studio_data/ai_switch.json"):
            self.assertTrue((files / rel).exists(), rel)
        self.assertFalse(list(self.to.rglob(".env")))
        self.assertFalse(list(self.to.rglob("projects.db")))
        self.assertFalse(list((self.to / "files").rglob("*.db")))     # databases only as checked copies

    def test_only_new_and_changed_files_and_nothing_deleted(self):
        self.assertEqual(self.run_backup()["files_copied"], 5)
        self.assertEqual(self.run_backup(now=datetime(2026, 11, 7, 1, 0))["files_copied"], 0)
        pdf = self.sd / "brief_lite" / "out" / "c0_brief.pdf"
        pdf.write_bytes(b"%PDF new version")
        os.utime(pdf, (time.time() + 10, time.time() + 10))
        (self.sd / "brief_lite" / "out" / "c0_render_A.png").unlink()  # deleted on C:
        rep = self.run_backup(now=datetime(2026, 11, 8, 1, 0))
        self.assertEqual(rep["files_copied"], 1)
        self.assertEqual((self.to / "files" / "brief_lite" / "out" / "c0_brief.pdf").read_bytes(), b"%PDF new version")
        self.assertTrue((self.to / "files" / "brief_lite" / "out" / "c0_render_A.png").exists())   # still here

    def test_the_newest_30_nights_are_kept(self):
        for day in range(35):
            self.run_backup(now=datetime(2026, 12, 1, 1, 0) + timedelta(days=day))
        nights = sorted(p.name for p in (self.to / "databases").iterdir())
        self.assertEqual(len(nights), 30)
        self.assertEqual(nights[-1], "2027-01-04")

    def test_never_leaves_d_short(self):
        rep = self.run_backup(free=49.0)
        self.assertEqual(rep["status"], "skipped")
        self.assertIn("50 GB must stay free", rep["detail"])
        self.assertFalse(self.to.exists())
        rep = self.run_backup(free=None)
        self.assertEqual(rep["status"], "failed")

    def test_no_chats_found_is_a_failure_not_a_pass(self):
        (self.sd / "brief_lite" / "lite.db").unlink()
        rep = self.run_backup()
        self.assertEqual(rep["status"], "failed")
        self.assertIn("weren't found", rep["detail"])


class ReportTests(unittest.TestCase):
    OK = {"status": "ok", "detail": "", "when": "2026-11-06T01:00", "free_gb": 512.3, "files_copied": 40, "files_mb": 120.4,
          "databases": {"lite.db": {"ok": True, "sessions": 57, "messages": 2310}}}

    def test_the_daily_email_line(self):
        self.assertEqual(B.summary(self.OK), "Backup of SameDay's chats (D:): done 2026-11-06 01:00 - 57 chats, 2,310 "
                                             "lines, 40 new files (120 MB); D: 512 GB free.")
        self.assertIn("SKIPPED", B.summary(dict(self.OK, status="skipped", detail="not copied: D: has 40 GB free")))
        self.assertIn("not run yet", B.summary(None))

    def test_emailed_when_it_fails_or_stops_running(self):
        self.assertIsNone(B.problem(self.OK, datetime(2026, 11, 6, 9, 0)))
        self.assertIsNone(B.problem(None, datetime(2026, 11, 6, 9, 0)))
        p = B.problem(dict(self.OK, status="failed", detail="lite.db: the copy didn't check out"), datetime(2026, 11, 6, 9, 0))
        self.assertEqual((p["key"], p["level"]), ("backup", "warn"))
        self.assertIn("didn't check out", p["title"])
        p = B.problem(self.OK, datetime(2026, 11, 7, 14, 0))           # 37 hours on: it stopped running
        self.assertIn("hasn't run since 2026-11-06 01:00", p["title"])


class OnTheServerTests(unittest.TestCase):
    def test_ship_it_carries_it(self):
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        self.assertIn('"sameday_backup.py"', deploy.split("$Files = @(", 1)[1].split("\n)", 1)[0])

    def test_the_watch_runs_it_and_emails_a_failure(self):
        src = (BACKEND / "sameday_watch.py").read_text(encoding="utf-8")
        self.assertIn("sameday_backup.backup(", src)
        self.assertIn("sameday_backup.problem(", src)
        self.assertIn('_opt("SAMEDAY_BACKUP_TO", r"D:\\SameDayBackups")', src)


if __name__ == "__main__":
    unittest.main()
