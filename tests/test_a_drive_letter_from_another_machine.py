"""A path from another machine may name a drive letter, and letters do not travel.

The Document Manager reports where it wrote a pack as a path seen from ITS host. The share it
writes to is one both machines reach, so this is insurance rather than a known failure — but
the FORM the path arrives in is not something we choose, and a drive letter is the one form
that breaks silently:

  * SDI_FILE_ROOTS is written in UNC, so `_within_a_root` rejects a letter path outright;
  * a letter is a per-logon-session mapping, so it can mean nothing to a service, or something
    different on the other machine.

Either way a folder that is genuinely readable is reported as unreachable, and the estimator
sees a successful extract they cannot import. Staging already failed in exactly this shape
("cannot find the path specified: 'K:\\'").
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"


@pytest.fixture()
def routes():
    sys.path.insert(0, str(_BACKEND))
    try:
        import estimate_routes  # noqa: PLC0415
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"the backend does not import here: {exc}")
    finally:
        if sys.path and sys.path[0] == str(_BACKEND):
            sys.path.pop(0)
    return estimate_routes


@pytest.fixture()
def mapped(routes, monkeypatch):
    monkeypatch.setattr(routes.config, "DRIVE_MAP",
                        {"K": r"\\sdi-dc01\shareddata$\Shared"}, raising=False)
    return routes


def test_a_mapped_letter_becomes_the_share_it_stands_for(mapped):
    assert mapped._to_unc(r"K:\Estimating\Completed\AI Estimating\packs\11650") == \
        r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\packs\11650"


def test_the_bare_root_of_a_mapped_drive_does_not_gain_a_stray_slash(mapped):
    assert mapped._to_unc("K:\\") == r"\\sdi-dc01\shareddata$\Shared"
    assert mapped._to_unc("K:") == r"\\sdi-dc01\shareddata$\Shared"


def test_a_unc_path_is_returned_untouched(mapped):
    """The expected case. Translation must cost nothing when there is nothing to translate."""
    p = r"\\sdi-dc01\shareddata$\Shared\Estimating\packs\11650"
    assert mapped._to_unc(p) == p


def test_an_unmapped_letter_is_left_alone_rather_than_guessed(mapped):
    """C: on another machine is that machine's own disk. Rewriting it to a share we happen to
    know would turn 'we cannot read this' into 'we read the wrong thing', which is worse."""
    assert mapped._to_unc(r"C:\DocMgr\output\11650") == r"C:\DocMgr\output\11650"


def test_the_mapping_is_case_insensitive_because_windows_is(mapped):
    assert mapped._to_unc(r"k:\packs").startswith(r"\\sdi-dc01")


def test_nothing_in_means_nothing_out(mapped):
    assert mapped._to_unc("") is None
    assert mapped._to_unc(None) is None


def test_the_default_mapping_matches_the_staging_root(routes):
    """K: and the UNC staging default describe the same folder, and they are configured in two
    places. If they ever disagree, one of the two is silently pointing somewhere else."""
    import config as backend_config

    mapped_k = (getattr(backend_config, "DRIVE_MAP", {}) or {}).get("K")
    if not mapped_k:
        pytest.skip("no K: mapping configured on this machine")
    staging = str(getattr(backend_config, "STAGING_ROOT", "") or "")
    if not staging.startswith("\\\\"):
        pytest.skip("staging root is not a UNC path on this machine")
    assert staging.upper().startswith(mapped_k.upper()), \
        f"K: maps to {mapped_k} but staging is at {staging} — one of them is wrong"
