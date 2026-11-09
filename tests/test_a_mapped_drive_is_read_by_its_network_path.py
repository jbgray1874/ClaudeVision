"""A path on a mapped drive letter is read through its network path, so W:\\ works in an
administrator window, a scheduled task or a service, where the letter itself does not exist (JG,
9 Nov 2026: the drawing index and the TTI pricer both reported W: "NOT READABLE from this window").
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import design_sweep as ds  # noqa: E402
import drawing_index as di  # noqa: E402
import drive_map as dm  # noqa: E402


def test_a_mapped_letter_becomes_its_network_path():
    env = {"SDI_DRIVE_MAP": r"K=\\sdi-dc01\shareddata$\Shared; W=\\fs01\design$\ "}
    assert dm.to_unc(r"W:\Design\Customers April 08 Onwards", env) == r"\\fs01\design$\Design\Customers April 08 Onwards"
    assert dm.to_unc("W:\\", env) == r"\\fs01\design$"
    assert dm.to_unc(r"K:\Estimating", env) == r"\\sdi-dc01\shareddata$\Shared\Estimating"
    assert dm.to_unc(r"\\fs01\x\y", env) == r"\\fs01\x\y", "a network path is left alone"
    assert dm.to_unc(r"C:\ClaudeVision", env) == r"C:\ClaudeVision", "an unmapped letter is left alone off Windows"


def test_unset_keeps_the_k_mapping_the_service_has_always_used():
    assert dm.to_unc(r"K:\x", {}) == r"\\sdi-dc01\shareddata$\Shared\x"


def test_the_index_and_the_sweep_read_their_roots_through_the_map():
    env = {"SDI_DRIVE_MAP": r"W=\\fs01\design$",
           "SDI_DRAWING_INDEX_ROOTS": r"W:\Design\Customers April 08 Onwards|W:\Prototype",
           "SDI_DESIGN_SWEEP_ROOT": r"W:\Design\Customers April 08 Onwards"}
    assert [str(r) for r in di.settings(env)["roots"]] == [r"\\fs01\design$\Design\Customers April 08 Onwards",
                                                           r"\\fs01\design$\Prototype"]
    assert str(ds.settings(env)["root"]) == r"\\fs01\design$\Design\Customers April 08 Onwards"
    src = (ROOT / "src" / "tti_pricer.py").read_text(encoding="utf-8")
    assert 'Path(to_unc(os.getenv("SDI_TTI_DESIGN_ROOT") or DEFAULT_DESIGN))' in src


def test_the_defaults_are_network_paths_and_w_maps_to_the_cad_share():
    assert dm.to_unc(r"W:\Production", {}) == r"\\sdi-dc01\CAD\Production"
    assert str(ds.settings({})["root"]) == r"\\sdi-dc01\CAD\Design\Customers April 08 Onwards"
    assert [str(r) for r in di.settings({})["roots"]] == [r"\\sdi-dc01\CAD\Design\Customers April 08 Onwards",
                                                       r"\\sdi-dc01\CAD\Prototype"]
    import tti_pricer as tp
    assert tp.DEFAULT_DESIGN.startswith("\\\\sdi-dc01\\CAD\\") and tp.DEFAULT_PROTOTYPE.startswith("\\\\sdi-dc01\\CAD\\")
    import live_enquiry_collector as lec
    assert str(lec._env_path("SDI_TEST_UNSET_PATH", r"K:\Estimating\x")) == r"\\sdi-dc01\shareddata$\Shared\Estimating\x"
