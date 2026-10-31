"""F198 desk-start: config-driven fresh Grok Build launch (no hard-coded desks)."""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "tools" / "desk" / "desk_start_plan.py"
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
EXAMPLE = ROOT / "tools" / "desk" / "desks.example.json"
README = ROOT / "tools" / "desk" / "README.md"


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
        "agent_file": "C:/desks/example-desk/agent.md",
        "model": "grok-example",
        "reasoning_effort": "high",
        "permission_mode": "default",
        "credential_target": "mill-desk/example-desk/github-pat",
        "lessons_label": "learn-example-desk",
        "lessons_byte_cap": 12000,
        "lessons_count_cap": 25,
        "handoff_letter_id": None,
        "handoff_query": "trail --label learn-example-desk",
        "add_dirs": ["C:/desks/example-desk/extra"],
        "first_message_template": "desk {desk}\nlearn-label {lessons_label}\ndo the open work first, then start mill connect-wait",
    }
    desk.update(desk_over)
    return {
        "office": {
            "mill_office": "example-office",
            "mill_connect_template": "mill --office {mill_office} connect {roster} {desk}",
            "roster": "example-roster",
            "export_before_restart": True,
            "launch_mode": "dashboard",
            "leader_socket": "",
        },
        "defaults": {
            "permission_mode": "default",
            "allow_bypass_permissions": False,
            "lessons_byte_cap": 12000,
            "lessons_count_cap": 25,
            "handoff_char_cap": 1500,
            "first_message_template": "desk {desk}\ndo the open work first, then start mill connect-wait",
        },
        "desks": [desk],
    }


def test_files_exist_and_example_validates():
    assert PLAN.is_file() and PS1.is_file() and EXAMPLE.is_file() and README.is_file()
    m = _mod()
    cfg = m.load_config(EXAMPLE)
    assert cfg["desks"][0]["name"] == "example-desk"
    assert "mill_office" in cfg["office"]


def test_no_hardcoded_real_desks_or_offices_in_script():
    # Build the live office alias from pieces so it never appears literally.
    live_office = "-".join(("aws", "mill"))
    src = PS1.read_text(encoding="utf-8")
    for banned in ("build-ui", "build-mill-shipper", live_office, "the-mill", "grok-tui"):
        assert banned not in src, f"script must not hard-code {banned}"
    plan_src = PLAN.read_text(encoding="utf-8")
    for banned in ("build-ui", "build-mill-shipper", live_office):
        assert banned not in plan_src


def test_positional_prompt_new_session_and_options():
    m = _mod()
    sid = "11111111-1111-1111-1111-111111111111"
    cfg = _cfg()
    cfg["office"]["launch_mode"] = "window"
    p = m.plan(config=cfg, desks=["example-desk"], session_id=sid)
    assert p["outcome"] == "ok"
    assert p["launch"] == "positional-prompt"
    assert p["launch_mode"] == "window"
    assert p["permission_mode"] == "default"
    assert p["session_id"] == sid
    argv = p["argv"]
    assert argv[0] == "grok"
    assert argv[argv.index("--cwd") + 1] == "C:/desks/example-desk/work"
    assert argv[argv.index("--agent") + 1].endswith("agent.md")
    assert argv[argv.index("--add-dir") + 1].endswith("extra")
    assert argv[argv.index("-m") + 1] == "grok-example"
    assert argv[argv.index("--reasoning-effort") + 1] == "high"
    assert argv[argv.index("-s") + 1] == sid
    assert argv[-1] == p["handoff"]
    assert "learn-label learn-example-desk" in p["handoff"]
    assert p["mill_connect"] == "mill --office example-office connect example-roster example-desk"


def test_never_resume_flags():
    m = _mod()
    cfg = _cfg()
    cfg["office"]["launch_mode"] = "window"
    p = m.plan(config=cfg, desks=["example-desk"], session_id=str(uuid.uuid4()))
    for bad in ("-r", "--resume", "-c", "--continue", "-p", "--single", "--fork-session"):
        assert bad not in p["argv"]
        assert bad not in p["window_argv"]


def test_bypass_refused_unless_allow_flag():
    m = _mod()
    cfg = _cfg(permission_mode="bypassPermissions")
    try:
        m.plan(config=cfg, desks=["example-desk"])
        assert False, "expected ConfigError"
    except m.ConfigError as e:
        assert "bypassPermissions" in str(e)
    cfg["defaults"]["allow_bypass_permissions"] = True
    cfg["office"]["launch_mode"] = "window"
    p = m.plan(config=cfg, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p["permission_mode"] == "bypassPermissions"
    assert p["argv"][p["argv"].index("--permission-mode") + 1] == "bypassPermissions"
    assert any("bypassPermissions" in w for w in p["warnings"])


def test_export_prior_keep_never_delete():
    m = _mod()
    prior = "22222222-2222-2222-2222-222222222222"
    p = m.plan(
        config=_cfg(),
        desks=["example-desk"],
        session_id=str(uuid.uuid4()),
        prior_session_id=prior,
    )
    assert p["export_argv"][0:3] == ["grok", "export", prior]
    assert p["export_path"].endswith(f"{prior}.md")
    assert "never delete" in p["export_note"]
    src = PS1.read_text(encoding="utf-8").lower()
    assert "never delete" in src
    assert "sessions delete" not in src


def test_seat_busy_and_missing_cred():
    m = _mod()
    busy = m.plan(config=_cfg(), desks=["example-desk"], seat_busy=True)
    assert busy["outcome"] == "refuse" and "never --take" in busy["reason"]
    miss = m.plan(config=_cfg(), desks=["example-desk"], cred_present=False)
    assert miss["outcome"] == "refuse"
    assert "mill-desk/example-desk/github-pat" in miss["reason"]


def test_lesson_caps_and_handoff_keeps_dont():
    m = _mod()
    lessons = [
        {"id": i, "created": f"2026-10-{i:02d}", "body": ("LEARN k: " + ("x" * 500))}
        for i in range(1, 40)
    ]
    kept = m.select_lessons(lessons, count_cap=25, byte_cap=12000)
    assert len(kept) <= 25
    assert sum(len(r["body"].encode()) for r in kept) <= 12000
    assert kept[0]["id"] == 39
    text = m.build_handoff_text(
        template="desk {desk}",
        desk="example-desk",
        fields={"lessons_label": "learn-example-desk"},
        cards=[{"id": i, "need_id": f"n{i}", "status": "claimed"} for i in range(1, 12)],
        letters=[{"id": 1000 + i, "gist": "old " + ("y" * 40)} for i in range(80)],
        holds=[],
        dont=["primary checkout"],
        char_cap=1500,
    )
    assert len(text) <= 1500
    assert "do-not-touch primary checkout" in text
    assert "card 1 " in text
    assert "card 11 " in text
    # letters are flexible and get dropped under the cap
    assert text.count("letter ") < 80


def test_unknown_desk_and_all():
    m = _mod()
    cfg = _cfg()
    cfg["desks"].append(
        {
            "name": "other-desk",
            "work_dir": "C:/desks/other/work",
            "export_dir": "C:/desks/other/exports",
            "credential_target": "mill-desk/other/github-pat",
        }
    )
    try:
        m.plan(config=cfg, desks=["nope"])
        assert False
    except m.ConfigError as e:
        assert "unknown desk" in str(e)
    multi = m.plan(config=cfg, desks=["all"], session_id=str(uuid.uuid4()))
    assert multi["count"] == 2
    assert {p["desk"] for p in multi["plans"]} == {"example-desk", "other-desk"}


def test_writes_allowed_only_desk_folders():
    m = _mod()
    p = m.plan(config=_cfg(), desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p["work_dir"] in p["writes_allowed"]
    assert p["export_dir"] in p["writes_allowed"]
    assert p["session_record"].endswith("session.json")


def test_ps1_and_readme_document_config_flags():
    src = PS1.read_text(encoding="utf-8")
    assert "Config" in src and "DryRun" in src and "Desk" in src
    assert "bypassPermissions" in src
    assert "grok 1.0.70" in src
    readme = README.read_text(encoding="utf-8")
    assert "-Config" in readme and "-Desk" in readme and "-DryRun" in readme
    assert "outside" in readme.lower()
    assert "Credential Manager" in readme
    assert "UNVERIFIED" in readme
    assert "dashboard" in readme
    assert "launch_mode" in PS1.read_text(encoding="utf-8")


def test_dashboard_mode_unverified_with_window_fallback():
    m = _mod()
    cfg = _cfg()
    cfg["office"]["launch_mode"] = "dashboard"
    p = m.plan(config=cfg, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert p["launch_mode"] == "dashboard"
    assert p["attach_status"] == "UNVERIFIED"
    assert p["argv"] == []
    assert p["window_argv"][0] == "grok"
    assert "-s" in p["window_argv"]
    assert "UNVERIFIED" in p["attach_note"]
    # example defaults to dashboard
    ex = m.plan(config_path=EXAMPLE, desks=["example-desk"], session_id=str(uuid.uuid4()))
    assert ex["launch_mode"] == "dashboard"
    assert ex["attach_status"] == "UNVERIFIED"


def test_bad_launch_mode_refused():
    m = _mod()
    cfg = _cfg()
    cfg["office"]["launch_mode"] = "sidecar"
    try:
        m.plan(config=cfg, desks=["example-desk"])
        assert False
    except m.ConfigError as e:
        assert "launch_mode" in str(e)


def test_dry_run_cli_on_example(tmp_path=None):
    m = _mod()
    raw = m.plan_to_json(
        m.plan(config_path=EXAMPLE, desks=["example-desk"], session_id=str(uuid.uuid4()))
    )
    data = json.loads(raw)
    assert data["dry_run"] is True
    assert data["would_launch"] is True
    assert data["launched"] is False
    assert data["help_source"].startswith("workstation grok --help")
    assert data["launch_mode"] == "dashboard"
    assert data["attach_status"] == "UNVERIFIED"
    assert data["window_argv"][0] == "grok"
