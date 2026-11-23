"""Row 29, 23 Nov 2026: the 08:40 crash left its unpriced status.json half filed; the service
restarted twice (each restart adds a restored note to the run's log), and the resume refused
the row's own evidence with "archive conflict", stopping the whole queue. Like the priced
archive, unpriced evidence is now filed under its content digest: every distinct snapshot
version is kept and none conflicts. A deliverable whose bytes truly changed still conflicts
and still stops, as test_archive_failure_is_not_downgraded_to_a_hold requires."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("unpriced_versions_batch", ROOT / "src/tti_concept_batch.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class Api:
    def __init__(self):
        self.email = b"the covering e-mail"
    def download(self, run_id, name):
        return self.email


def _snapshot(log):
    return {"run_id": "4a1540d19e54", "status": "done", "client": "TTI",
            "drawing_number": "TTI-C-8484cc0233aa3f2f2cff-R2", "units": 2,
            "engine_price_gbp": None, "price_validated": False, "log": list(log),
            "deliverables": [{"name": "covering_email.html"}]}


ITEM = {"reference": "TTI-C-8484cc0233aa3f2f2cff-R2", "row": 29, "quantity": 2}
ENTRY = {"run_id": "4a1540d19e54"}


def test_refiling_after_a_crash_is_a_new_version_not_a_conflict(tmp_path):
    arc = b.Archive(tmp_path / "c", tmp_path / "k")
    api = Api()
    b.archive_unpriced(api, arc, ITEM, ENTRY, _snapshot(["engine started"]), "no price")
    # The service restarted in between: the same run's snapshot now carries one more line.
    b.archive_unpriced(api, arc, ITEM, ENTRY, _snapshot(["engine started", "restored after a restart"]), "no price")
    base = tmp_path / "c" / ITEM["reference"] / "unpriced" / "4a1540d19e54"
    versions = sorted(p.name for p in base.glob("status-*.json"))
    assert len(versions) == 2, versions
    assert (base / "HOLD.json").exists() and (base / "covering_email.html").exists()


def test_a_deliverable_whose_bytes_changed_still_stops(tmp_path):
    arc = b.Archive(tmp_path / "c", tmp_path / "k")
    api = Api()
    b.archive_unpriced(api, arc, ITEM, ENTRY, _snapshot(["engine started"]), "no price")
    api.email = b"different bytes for the same name"
    with pytest.raises(ValueError, match="archive conflict"):
        b.archive_unpriced(api, arc, ITEM, ENTRY, _snapshot(["engine started"]), "no price")
