"""27 Sep 2026: the drawing picker said "Folder not found" for the Live Enquiry root while the
VPN was down. The folder existed; the share could not be reached. Three situations produced one
sentence, and each sends a person somewhere different (D-285)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"))

from share_reach import folder_missing_detail, root_of  # noqa: E402

_ROOT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry"
_ROOTS = [_ROOT, r"C:\ClaudeVision\output"]


def _isdir_with(present):
    _p = {os.path.normcase(os.path.normpath(x)) for x in present}
    return lambda p: os.path.normcase(os.path.normpath(str(p))) in _p


def test_the_root_itself_unreachable_names_the_share_and_the_vpn():
    msg = folder_missing_detail(_ROOT, _ROOTS, isdir=_isdir_with([]))
    assert "not reachable" in msg and _ROOT in msg
    assert "VPN" in msg and "share" in msg
    assert "Folder not found" not in msg, "the folder was not the thing that had gone"


def test_a_local_root_that_is_absent_is_not_blamed_on_the_vpn():
    msg = folder_missing_detail(r"C:\ClaudeVision\output\reports", _ROOTS, isdir=_isdir_with([]))
    assert "not reachable" in msg and "VPN" not in msg


def test_a_missing_leaf_under_a_live_root_says_the_parent_is_there():
    target = _ROOT + r"\12567 Tesco"
    msg = folder_missing_detail(target, _ROOTS, isdir=_isdir_with([_ROOT]))
    assert msg.startswith("Folder not found: " + target)
    assert "above it is there" in msg


def test_a_missing_ancestor_is_named():
    target = _ROOT + r"\12567 Tesco\Drawings\Rev B"
    msg = folder_missing_detail(target, _ROOTS, isdir=_isdir_with([_ROOT]))
    assert "12567 Tesco under" in msg and "moved or renamed" in msg


def test_a_path_under_no_root_is_still_a_plain_not_found():
    msg = folder_missing_detail(r"D:\elsewhere", _ROOTS, isdir=_isdir_with([]))
    assert msg == r"Folder not found: D:\elsewhere"
    assert root_of(r"D:\elsewhere", _ROOTS) is None
