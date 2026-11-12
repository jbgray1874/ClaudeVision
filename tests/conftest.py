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
