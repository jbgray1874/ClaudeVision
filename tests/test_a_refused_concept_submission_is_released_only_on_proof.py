"""A REFUSED CONCEPT SUBMISSION IS RELEASED ONLY ON PROOF (21 Nov 2026).

The first live concept row met an HTTP 500 while the service was staging it (no PyMuPDF), before
any run existed. Its durable state already said 'submitting', and a resume rightly will not send
it again by itself. --release-uncertain lets an operator name the row; it is released only when
the entry is 'submitting' with no run id, is old enough for a slow acceptance to have shown, and
the service holds no run at all under the row's reference. Both quantity switches are one option.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_concept_batch as batch  # noqa: E402

_spec = importlib.util.spec_from_file_location("_concept_fx", ROOT / "tests" / "test_tti_concept_batch.py")
_fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fx)


class Refusing(_fx.FakeAPI):
    """The service answers the POST with an error and creates no run."""
    def start(self, body):
        self.posts.append(body)
        raise RuntimeError("HTTP Error 500: Internal Server Error")


def _stuck(tmp_path):
    path, plan, pics, archive, _ = _fx.setup(tmp_path)
    api = Refusing()
    with pytest.raises(RuntimeError):
        _fx.run(plan, pics, archive, api, selected_rows=[3])
    state = batch.read_json(archive.roots[0] / "state.json")
    assert [e["phase"] for e in state["entries"].values()] == ["submitting"]
    return plan, pics, archive, api


def _later(): return datetime.now(timezone.utc) + timedelta(hours=1)


def test_a_resume_alone_never_resends_it(tmp_path):
    plan, pics, archive, api = _stuck(tmp_path)
    with pytest.raises(RuntimeError, match="uncertain submission"):
        _fx.run(plan, pics, archive, api, selected_rows=[3])
    assert len(api.posts) == 1


def test_released_when_the_service_holds_no_run_then_sent_once(tmp_path):
    plan, pics, archive, api = _stuck(tmp_path)
    batch.release_uncertain(archive, api, [3], clock=_later)
    for root in archive.roots:
        assert batch.read_json(root / "state.json")["entries"] == {}
        assert any("UNCERTAIN SUBMISSION RELEASED" in f.read_text() for f in (root / "events").iterdir())
    good = _fx.FakeAPI()
    assert _fx.run(plan, pics, archive, good, selected_rows=[3]) == 0
    assert len(good.posts) == 1


def test_not_released_too_soon_or_when_a_run_exists_or_when_not_uncertain(tmp_path):
    plan, pics, archive, api = _stuck(tmp_path)
    with pytest.raises(RuntimeError, match="wait"):
        batch.release_uncertain(archive, api, [3])                       # seconds old
    ref = next(iter(batch.read_json(archive.roots[0] / "state.json")["entries"]))
    api.runs["00000000000a"] = {"run_id": "00000000000a", "client": "TTI", "drawing_number": ref,
                                "units": 2, "status": "queued"}
    with pytest.raises(RuntimeError, match="holds run"):
        batch.release_uncertain(archive, api, [3], clock=_later)
    with pytest.raises(RuntimeError, match="no single entry"):
        batch.release_uncertain(archive, Refusing(), [4], clock=_later)   # a row never submitted
    assert len(batch.read_json(archive.roots[0] / "state.json")["entries"]) == 1


def test_both_quantity_switches_are_one_option():
    src = (ROOT / "src" / "tti_concept_batch.py").read_text(encoding="utf-8")
    assert "'--assume-missing-quantity-one','--blank-quantity-as-one',dest='assume_missing_quantity_one'" in src
