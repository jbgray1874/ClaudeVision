"""The ENGINE'S config is cached before any test can shadow the name.

Two modules in this repository are called config: the engine's (src/config.py — the
density and vocabulary tables) and the portal backend's (sdi-intelligence-backend/
config.py). Both are imported bare as `import config`, so whichever directory reaches
sys.path first wins FOR THE WHOLE PROCESS. Test files that exercise the backend prepend
its directory at import time, and in a hand-picked subset collected before anything had
imported the engine's config, every density lookup silently resolved against the
backend's table-less config and the sheet checks weighed nothing (sighted_weight_kg
None). The full suite only ever passed because alphabetical collection cached the
engine's config first — this file makes that de-facto order the law for every ordering.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402,F401  — the engine's, cached in sys.modules for the process


# ── A PRIVATE STATE FOLDER FOR EVERY TEST (D-618) ─────────────────────────────────────────
# The estimating service now keeps every run on disk under its state folder and reads them
# back on import (restart-safe history). Left alone, the suite would write runs into the
# home folder and each fresh import of the routes would restore runs from earlier tests. A
# test that wants a particular folder still sets SDI_STATE_DIR itself.
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _private_state_folder(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path_factory.mktemp("sdi-state")))
    # NO TEST DROPS A PACK INTO THE CHECKOUT'S OWN chatgptdropoff (12 Nov 2026). A test that
    # wants the drop-off sets SDI_PACK_DROPOFF_DIR to its own folder.
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")
