"""12161-03-GA and 12773-01-GA (11 Nov 2026): the quote's header showed a plain yellow circle,
no we.are.sdi logo. Both ran on slot 2, whose checkout is a git worktree without the logo files
(they are not in git). A slot's checkout takes the main checkout's logo folder."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as cq  # noqa: E402


def test_a_slot_checkout_without_logos_uses_the_main_checkouts(tmp_path):
    main = tmp_path / "ClaudeVision" / "assets" / "customer_logos"
    main.mkdir(parents=True)
    (main / "wearesdi.svg").write_text("<svg></svg>")
    slot = tmp_path / "ClaudeVision-s2"
    (slot / "assets" / "customer_logos").mkdir(parents=True)
    (slot / "assets" / "customer_logos" / "README.md").write_text("logos are not in git")
    assert cq.logos_folder(slot) == str(main)
    assert cq.logos_folder(tmp_path / "ClaudeVision") == str(main)


def test_a_slot_with_its_own_logos_or_no_main_keeps_its_own(tmp_path):
    slot = tmp_path / "ClaudeVision-s2" / "assets" / "customer_logos"
    slot.mkdir(parents=True)
    assert cq.logos_folder(tmp_path / "ClaudeVision-s2") == str(slot), "no main checkout beside it"
    (tmp_path / "ClaudeVision" / "assets" / "customer_logos").mkdir(parents=True)
    (slot / "wearesdi.png").write_bytes(b"x")
    assert cq.logos_folder(tmp_path / "ClaudeVision-s2") == str(slot)
