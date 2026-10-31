# -*- coding: utf-8 -*-
"""Guards, score, and bless. The office run is the CLI, not this file."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "freeze_harness", ROOT / "tools" / "freeze_harness.py"
)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_refuses_office_remote_and_live_db() -> None:
    assert harness._refuse(["run", "A1", "--office", "office-alias"]) == "refused --office"
    assert harness._refuse(["run", "A1", "--db", "agent_coord"]) == "refused db name"
    assert harness._refuse(["run", "A1", "--url", "https://example.com/"]) == "refused remote url"
    assert harness._refuse(["run", "A1", "--url", "http://127.0.0.1:9/"]) == ""


def test_main_refuses_before_a_book(capsys) -> None:
    assert harness.main(["run", "A1", "--desk", "freeze-desk", "--office", "office-alias"]) == 2
    assert "refused --office" in capsys.readouterr().out


def test_judge_rows() -> None:
    assert harness.judge("A1", {"frame": "todo:TODO", "verb": "todo"})[0] == "green"
    assert harness.judge("A1", {"frame": "PING", "verb": "", "mail_rows": 0})[0] == "green"
    assert harness.judge("A1", {"frame": "PING", "verb": "inbox", "mail_rows": 0})[0] == "red"
    assert harness.judge(
        "A2",
        {"verb": "todo", "wrong": 1, "retry": 1, "resent_same": False},
    )[0] == "green"
    assert harness.judge(
        "A2",
        {"verb": "todo", "wrong": 1, "retry": 2, "resent_same": False},
    )[0] == "red"
    assert harness.judge("A7", {"decision": "work", "sentinel_ran": False})[0] == "green"
    assert harness.judge("A7", {"decision": "work", "sentinel_ran": True})[0] == "red"
    assert harness.judge(
        "F3",
        {"same_req": True, "mail_rows": 1, "fanout": 1, "send_runs": 1},
    )[0] == "green"
    assert harness.judge(
        "F3",
        {"same_req": True, "mail_rows": 2, "fanout": 1, "send_runs": 1},
    )[0] == "red"


def test_client_exit_line(tmp_path) -> None:
    harness.note_client_exit(tmp_path, 2, "A2")
    text = (tmp_path / "mill-perf.log").read_text(encoding="utf-8")
    assert "op=hint.client_exit" in text
    assert "code=2" in text
    assert "row=A2" in text


def test_compare_and_bless(tmp_path) -> None:
    green = tmp_path / "green.json"
    rec = {
        "run_id": "abc",
        "row": "A7",
        "frame": "todo:TODO",
        "verb": "",
        "wrong": 0,
        "retry": 0,
        "decision": "work",
        "err": "",
        "mail_rows": 0,
        "fanout": 0,
        "same_req": False,
        "result": "green",
    }
    (tmp_path / "A7.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert harness.cmd_bless("A7", "abc", tmp_path, green) == 0
    assert harness.cmd_compare("A7", tmp_path, green) == 0
    other = dict(rec)
    other["run_id"] = "def"
    other["decision"] = "wake"
    other["result"] = "red"
    with (tmp_path / "A7.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(other) + "\n")
    assert harness.cmd_compare("A7", tmp_path, green) == 1


def test_tool_stays_out_of_the_wheel() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["agent_coord*"]' in text
    assert "tools/freeze_harness.py" not in text


def test_f3_arm_counts_a_mail_push_sent_with_keyword_args(tmp_path, monkeypatch) -> None:
    """#795: push_mail calls emit(..., reason=, room=); the F3 counter must take them."""
    from agent_coord.server import push as push_mod
    from agent_coord.server.api.mill import rpc

    seen: list[tuple] = []

    def fake_emit(cn, who, kind, payload, *, reason="addressed", room=None):
        seen.append((who, kind, reason, room))
        return "sent"

    monkeypatch.setattr(push_mod, "emit", fake_emit)
    monkeypatch.setitem(rpc.HANDLERS, "send", rpc.HANDLERS["send"])
    obs: dict = {}
    harness._arm("F3", tmp_path, "freeze-desk", obs)
    out = push_mod.emit(None, "freeze-peer", "mail", {"id": 1}, reason="addressed", room="r1")
    assert out == "sent"
    assert seen == [("freeze-peer", "mail", "addressed", "r1")]
    assert obs["fanout"] == 1
    push_mod.emit(None, "freeze-peer", "todo", {"id": 2})
    assert obs["fanout"] == 1
