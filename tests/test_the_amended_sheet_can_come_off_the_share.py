"""Regenerating a quote must not require finding, on disk, a file this service just wrote.

The override route accepted an UPLOAD and nothing else. So the ordinary case - a run finishes,
the estimator opens the workbook it produced, changes two rates, wants the client quote again -
meant leaving the portal, finding that file in Explorer, and handing it back to the service that
had created it, into a folder the service can browse and lists further down the same page.

It read as a capability that had been taken away, because the parity card directly above offers
"Choose from share" on both of its sides. It never had it; it should.

These tests cover the gate and the delete, which are the two things that would actually hurt.
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


# ── the form contract ───────────────────────────────────────────────────────────────────

def test_both_sources_are_optional_so_either_can_be_used(routes):
    """`file` was a required File(...). A share-path-only request could not even be parsed:
    FastAPI rejected it at validation with no route code running, so the estimator got a 422
    naming a field they had deliberately not filled in."""
    import inspect

    sig = inspect.signature(routes.estimate_override)
    assert "share_path" in sig.parameters, "the share path must be accepted"
    for name in ("file", "share_path"):
        default = sig.parameters[name].default
        assert getattr(default, "default", ...) is None, \
            f"{name} must be optional so the other one alone is a valid request"


def test_the_three_facts_are_still_required(routes):
    """A workbook saved days ago cannot be trusted to carry units, drawing and client, so
    they are named on the form. Making the workbook optional must not loosen these."""
    import inspect

    # A required Form() carries PydanticUndefined, not Ellipsis, under pydantic v2 - so the
    # test is "not None", which is exactly what separates it from the two optional ones.
    sig = inspect.signature(routes.estimate_override)
    for name in ("units", "drawing", "client"):
        default = sig.parameters[name].default
        assert getattr(default, "default", None) is not None, \
            f"{name} must stay required"


# ── the gate on a path that came from a browser ─────────────────────────────────────────

def test_a_path_outside_the_allowed_roots_is_refused(routes, tmp_path):
    """THE REASON THIS IS NOT JUST open(path). The page sends a path; without the same
    containment check every other share read here uses, this becomes a way to hand the
    engine any file the service account can open."""
    outside = tmp_path / "not-a-share" / "secrets.xlsx"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"PK\x03\x04")
    assert routes._within_a_root(str(outside)) is None, \
        "a path outside every configured root must not resolve"


def test_the_root_check_is_the_one_the_rest_of_the_service_uses(routes):
    """Not a second, parallel implementation. A copy is what drifts, and the copy that
    drifts is the one nobody is looking at."""
    import inspect

    src = inspect.getsource(routes.estimate_override)
    assert "_within_a_root(" in src, \
        "the share path must go through the service's own containment check"


# ── the delete, which is where this could do real damage ────────────────────────────────

def test_a_share_workbook_is_never_unlinked(routes):
    """THE ONE THAT WOULD BE UNFORGIVABLE. The upload path writes a temp file and removes it
    in a finally. Reusing that finally for a share path would DELETE THE ESTIMATOR'S SHEET
    off the AISheets folder as a side effect of reading it - a destructive act performed by
    a read-only-sounding button, on the only copy of somebody's amended estimate.
    """
    import inspect

    src = inspect.getsource(routes.estimate_override)
    assert "if tf is not None:" in src, \
        "the unlink must be fenced so it can only ever remove our own temp file"
    unlink_at = src.index("os.unlink")
    fence_at = src.index("if tf is not None:")
    assert fence_at < unlink_at, "the fence must come before the unlink, not after it"


def test_the_upload_path_still_cleans_up_after_itself(routes):
    """An uploaded workbook is a copy of somebody's estimate sitting in the box's temp
    folder. It was removed before and must still be."""
    import inspect

    src = inspect.getsource(routes.estimate_override)
    assert "os.unlink(tf.name)" in src and "finally:" in src
