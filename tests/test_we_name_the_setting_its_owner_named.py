"""Ask for a setting by the name its owner gave it.

The Document Manager's own guide documents two settings for callers:

    DOCMGR_BASE_URL
    DOCMGR_ACCESS_SECRET

Ours asked for `SDI_DM_API_BASE` and `SDI_DM_API_KEY`. The client accepted both all along — the
DOCMGR names are in `_ENV_BASE_ALIASES` and `_ENV_KEY_ALIASES` — but every message a person could
read named OUR alias first, and the .env checker printed the SDI_ ones.

So an estimator, an error message and the tool's author each used a different word for the same
setting. It cost an afternoon: the settings were checked in the wrong file, then reported to the
author as missing, and he replied that he had never heard of them — because he hadn't.

A message that names a setting nobody else calls by that name is worse than no message, because
it is followed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"

_FACING = ("docmgr.py", "estimate_routes.py", "sdi-estimating-intelligence.html")


@pytest.mark.parametrize("name", _FACING)
def test_no_user_facing_message_asks_for_the_sdi_alias_first(name):
    """The alias may still be READ — accepting both costs nothing. It must not be what we ASK
    for, because that is the word somebody carries to the tool's author."""
    text = (_BACKEND / name).read_text(encoding="utf-8")
    at = 0
    while True:
        hits = [text.find(n, at) for n in ("SDI_DM_API_BASE", "SDI_DM_API_KEY")]
        hits = [h for h in hits if h >= 0]
        if not hits:
            break
        i = min(hits)
        # A window rather than a line: the qualifier that makes the mention acceptable often
        # falls on the next line, and a per-line check failed on correct wording.
        window = text[max(0, i - 240):i + 240]
        assert "accepted" in window or "alias" in window, (
            f"{name}: this asks for our own name rather than the documented one:\n  "
            f"{text[max(0, i - 120):i + 120].strip()}")
        at = i + 1


@pytest.mark.parametrize("name", _FACING)
def test_the_documented_names_are_the_ones_offered(name):
    text = (_BACKEND / name).read_text(encoding="utf-8")
    assert "DOCMGR_BASE_URL" in text and "DOCMGR_ACCESS_SECRET" in text


def test_both_names_still_work():
    """Renaming the message must not break anybody who already set the SDI_ names."""
    src = (_BACKEND / "docmgr.py").read_text(encoding="utf-8")
    assert '_ENV_BASE_ALIASES = ("DOCMGR_BASE_URL",)' in src
    assert "DM_API_BASE" in src, "the SDI_ alias must still be read via config"


def test_the_401_names_the_secret_its_owner_issued():
    """A 401 is the shared secret every time. Naming the wrong variable sends somebody to change
    a setting that was never being read."""
    src = (_BACKEND / "docmgr.py").read_text(encoding="utf-8")
    at = src.index("refused our access secret (401)")
    assert "DOCMGR_ACCESS_SECRET" in src[at:at + 260]
