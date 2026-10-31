"""F222: desk-start lean first message + context_restart_tokens (card 930).

Grok Build compacts near 200k/256k. Desks must sit with connect-wait in the
foreground (grok-tui recipe) and ask for a fresh restart near the configured
token threshold (default 190000). Never resume, never compact.
"""
from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "tools" / "desk" / "desk_start_plan.py"
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
EXAMPLE = ROOT / "tools" / "desk" / "desks.example.json"
README = ROOT / "tools" / "desk" / "README.md"
ROW = ROOT / "docs" / "security" / "regression" / "F222.md"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _mod():
    spec = importlib.util.spec_from_file_location("desk_start_plan", PLAN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _cfg(**desk_over):
    desk = {
        "name": "example-desk",
        "work_dir": "C:/desks/example-desk/work",
        "export_dir": "C:/desks/example-desk/exports",
        "credential_target": "mill-desk/example-desk/github-pat",
        "lessons_label": "learn-example-desk",
    }
    desk.update(desk_over)
    return {
        "office": {
            "mill_office": "example-office",
            "mill_connect_template": "mill --office {mill_office} connect {roster} {desk}",
            "roster": "example-roster",
            "export_before_restart": True,
            "launch_mode": "window",
            "leader_socket": "",
        },
        "defaults": {
            "permission_mode": "default",
            "allow_bypass_permissions": False,
            "lessons_byte_cap": 12000,
            "lessons_count_cap": 25,
            "handoff_char_cap": 1500,
        },
        "desks": [desk],
    }


def test_default_first_message_is_lean_foreground_sit():
    m = _mod()
    cfg = _cfg()  # no desk/default first_message_template override
    p = m.plan(config=cfg, desks=["example-desk"], session_id=str(uuid.uuid4()))
    handoff = p["handoff"]
    assert "connect-wait" in handoff
    assert "FOREGROUND" in handoff or "foreground" in handoff.lower()
    assert "never background" in handoff.lower() or "never &, never" in handoff.lower() or "never &" in handoff.lower()
    assert "mill-desk" in handoff
    assert "mill-build-assist" in handoff  # named so the desk knows not to load it
    assert "todo --mine" in handoff
    assert "backlog" in handoff.lower() or "scan the board" in handoff.lower()
    assert "human chat" in handoff.lower()
    # lean: must not burn tokens on a long backlog recipe
    assert len(handoff) < 1200, f"default first message too long ({len(handoff)} chars)"


def test_context_restart_tokens_default_and_override():
    m = _mod()
    cfg = _cfg()
    p = m.plan(config=cfg, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p["context_restart_tokens"] == 190_000
    assert "190000" in p["handoff"] or "190_000" in p["handoff"] or "context" in p["handoff"].lower()
    # fresh restart instruction, never resume/compact
    low = p["handoff"].lower()
    assert "fresh" in low and ("never resume" in low or "desk-start" in low)
    assert "never" in low and "compact" in low

    # defaults override
    cfg2 = _cfg()
    cfg2["defaults"]["context_restart_tokens"] = 175000
    p2 = m.plan(config=cfg2, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p2["context_restart_tokens"] == 175000

    # desk-level beats defaults
    cfg3 = _cfg(context_restart_tokens=165000)
    cfg3["defaults"]["context_restart_tokens"] = 175000
    p3 = m.plan(config=cfg3, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p3["context_restart_tokens"] == 165000


def test_example_and_ps1_and_readme_plumb_context_restart():
    m = _mod()
    cfg = m.load_config(EXAMPLE)
    assert int(cfg["defaults"]["context_restart_tokens"]) == 190000
    ex = m.plan(config_path=EXAMPLE, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert ex["context_restart_tokens"] == 190000
    assert "connect-wait" in ex["handoff"]

    ps1 = PS1.read_text(encoding="utf-8")
    assert "context_restart_tokens" in ps1
    assert "190000" in ps1 or "190_000" in ps1
    # default template in ps1 must mention foreground sit
    assert "connect-wait" in ps1
    assert re.search(r"FOREGROUND|foreground", ps1)

    readme = README.read_text(encoding="utf-8")
    assert "context_restart_tokens" in readme
    assert "190" in readme
    # lessons byte cap: planner enforces; ps1 does not assemble lessons
    assert "lessons_byte_cap" in readme
    assert "select_lessons" in readme or "planner" in readme.lower() or "does not assemble" in readme.lower()


def test_lessons_byte_cap_still_enforced_by_planner():
    """card 930: enforce if assembled; planner already does via select_lessons."""
    m = _mod()
    lessons = [
        {"id": i, "created": f"2026-10-{i:02d}", "body": ("LEARN k: " + ("x" * 800))}
        for i in range(1, 30)
    ]
    kept = m.select_lessons(lessons, count_cap=25, byte_cap=12000)
    assert sum(len(r["body"].encode()) for r in kept) <= 12000
    assert len(kept) <= 25


def test_f222_row_and_matrix():
    assert ROW.is_file(), "docs/security/regression/F222.md missing"
    line = ROW.read_text(encoding="utf-8")
    assert "| F222" in line
    assert "context_restart_tokens" in line or "190" in line
    assert "test_desk_start_restart_222" in line
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "| F222" in matrix
