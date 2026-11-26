"""Tests for the staging loader, using a stand-in connection (no SQL Server needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m2f.db_load import SCHEMA_FILE, load_staging, schema_batches  # noqa: E402
from m2f.tracker_import import ForecastLine, ImportIssue, Project, TrackerImport  # noqa: E402


class FakeCursor:
    def __init__(self, log):
        self.log, self.fast_executemany = log, False

    def execute(self, sql, *params):
        self.log.append(("execute", sql, params))

    def executemany(self, sql, rows):
        self.log.append(("executemany", sql, rows))

    def fetchone(self):
        return (7,)


class FakeConn:
    def __init__(self, fail_on=None):
        self.log, self.committed, self.rolled_back, self.fail_on = [], False, False, fail_on

    def cursor(self):
        cur = FakeCursor(self.log)
        if self.fail_on:
            real = cur.executemany

            def executemany(sql, rows):
                if self.fail_on in sql:
                    raise RuntimeError("insert failed")
                real(sql, rows)
            cur.executemany = executemany
        return cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _result():
    r = TrackerImport(source="tracker.xlsx")
    r.projects.append(Project("BUK-004", "Current -Boots", 4, True, "Boots UK", "Boots UK", "Alpha",
                              {"pm": "Conor"}, {"SDI Notes": "x"}))
    r.forecast_lines.append(ForecastLine("BUK-004", "Current -Boots", "AL4", "2025-10", "100.00",
                                         "100", "value", "Risk", "FF0000"))
    r.issues.append(ImportIssue("status_unclassified", "decision", "Colour not on legend.",
                                tab="Current -Boots", cell="AL4", review_key="BUK-004"))
    return r


def test_schema_splits_into_batches_without_comment_only_batches():
    batches = schema_batches(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert "IF SCHEMA_ID('m2f') IS NULL" in batches[0]
    assert not any(b.upper() == "GO" for b in batches)
    assert any("CREATE TABLE m2f.forecast_line" in b for b in batches)
    assert any("CREATE OR ALTER VIEW m2f.v_forecast_month" in b for b in batches)


def test_load_staging_writes_batch_rows_and_issues():
    conn = FakeConn()
    assert load_staging(conn, _result(), imported_by="tester") == 7
    many = {sql.split()[1]: rows for kind, sql, rows in conn.log if kind == "executemany"}
    assert many["m2f.stg_project"][0][:4] == (7, "BUK-004", "Current -Boots", 4)
    assert many["m2f.stg_forecast_line"][0][4:6] == ("2025-10-01", "100.00")
    assert many["m2f.import_issue"][0][1:3] == ("status_unclassified", "decision")
    assert conn.committed and not conn.rolled_back


def test_load_staging_rolls_back_on_failure():
    conn = FakeConn(fail_on="stg_forecast_line")
    try:
        load_staging(conn, _result())
    except RuntimeError:
        pass
    assert conn.rolled_back and not conn.committed
