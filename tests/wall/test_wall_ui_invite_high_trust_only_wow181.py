# -*- coding: utf-8 -*-
"""INVITE strip/chip high-trust only (Host lock)."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOARD = ROOT / "default" / "board.html"
BOOT = ROOT / "default" / "boot.js"


def test_invite_chip_stays_hidden_during_redesign():
    src = BOOT.read_text(encoding="utf-8")
    gate = src.split("function wallInviteGateOk(", 1)[1].split("function wallApplyInviteGate(", 1)[0]
    assert "return false" in gate
    assert 'return t === "high"' not in gate
    assert "wallIsAdminChrome" not in gate
    html = BOARD.read_text(encoding="utf-8")
    strip = html.split('id="strip"', 1)[1].split("</div>", 1)[0]
    assert "wall-invite-box" not in strip
    assert ">INVITE<" not in strip
    rebuild = src.split("function strip(", 1)[1].split("function isMillNeedId(", 1)[0]
    assert "wall-invite-box" not in rebuild
    assert "inviteChip" not in rebuild


def test_apply_gate_hides_chip_and_disables_mint():
    src = BOOT.read_text(encoding="utf-8")
    apply = src.split("function wallApplyInviteGate(", 1)[1].split("function wallStubSeatToken(", 1)[0]
    assert 'sec.hidden = !_wallInviteGateOk' in apply or "sec.hidden = !_wallInviteGateOk" in apply
    assert "box.hidden = !_wallInviteGateOk" in apply
    assert "mint.disabled = !_wallInviteGateOk" in apply
    # mint click still re-checks gate
    wire = src.split("function wallWelcomeWire(", 1)[1].split("/* wallWelcomeWire+Boot", 1)[0]
    assert "wallInviteGateOk()" in wire
    assert 'if (!_wallInviteGateOk && !wallInviteGateOk()) return;' in wire.replace(" ", "") or (
        "if (!_wallInviteGateOk && !wallInviteGateOk()) return;" in wire
    )


def test_human_welcome_brief_and_seat_url():
    src = BOOT.read_text(encoding="utf-8")
    assert "pip install -U the-mill" not in src
    assert "wakeup paste" not in src
    assert "docs/JOIN.md" in src
    assert "/welcome?desk=" in src
    assert "function wallMintInvite(" in src
    html = BOARD.read_text(encoding="utf-8")
    assert "Workstation once" not in html
    assert 'id="wall-welcome-join"' in html
    assert "Generate URL" in html
    assert 'id="wall-welcome-x"' in html
    assert 'class="dismiss"' in html
    assert "Enter Nest" not in html
    card = html.split('id="wall-welcome"', 1)[1].split('id="howto-card"', 1)[0]
    assert "A seat is one URL for one agent." in card
    assert "mill join" not in card
