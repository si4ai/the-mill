"""F212 (head-branch-cold-measure): tools/cold_measure_head.py stages a PR-head kit."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "cold_measure_head", ROOT / "tools" / "cold_measure_head.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _fake_head(tmp_path: Path) -> Path:
    head = tmp_path / "head"
    (head / "docs" / "protocol").mkdir(parents=True)
    (head / "docs" / "JOIN.md").write_text("# JOIN\njoin steps\n", encoding="utf-8")
    (head / "docs" / "protocol" / "skill.md").write_text(
        "---\nname: mill-desk\n---\n# Mill desk\n", encoding="utf-8"
    )
    (head / "pyproject.toml").write_text('[project]\nname = "the-mill"\nversion = "0.0.0"\n', encoding="utf-8")
    return head


def test_module_imports():
    mod = _mod()
    assert hasattr(mod, "stage_kit")
    assert hasattr(mod, "verdict_body")
    assert hasattr(mod, "main")
    assert hasattr(mod, "is_live_mill")


def test_stage_kit_copies_join_and_skill_and_records_shas(tmp_path: Path) -> None:
    mod = _mod()
    head = _fake_head(tmp_path)
    out = tmp_path / "kit-out"
    manifest = mod.stage_kit(head, out, allow_dirty=True)
    join_text = (head / "docs" / "JOIN.md").read_text(encoding="utf-8")
    skill_text = (head / "docs" / "protocol" / "skill.md").read_text(encoding="utf-8")
    assert (out / "JOIN.md").read_text(encoding="utf-8") == join_text
    assert (out / "mill-desk" / "SKILL.md").read_text(encoding="utf-8") == skill_text
    assert not (out / "grok-bot").exists()
    assert "root" not in manifest
    assert manifest["join_sha"] == _sha(join_text)
    assert manifest["skill_sha"] == _sha(skill_text)
    assert (out / "manifest.json").is_file()
    assert (out / "recipe.md").is_file()
    recipe = (out / "recipe.md").read_text(encoding="utf-8")
    assert "What is desk grok-tui doing" in recipe
    assert "commands" in recipe and "wrong" in recipe and "retries" in recipe
    assert "join" in recipe.lower() and "leave" in recipe.lower()
    assert "wake-on addressed" in recipe


def test_refuse_live_mill_marker(tmp_path: Path) -> None:
    mod = _mod()
    head = _fake_head(tmp_path)
    live = tmp_path / "live-mill"
    live.mkdir()
    (live / ".live-mill-marker").write_text("live\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        mod.stage_kit(head, live, refuse_live=True, allow_dirty=True)
    assert ei.value.code == 2


def test_refuse_out_that_holds_path_mill(tmp_path: Path, monkeypatch) -> None:
    mod = _mod()
    out = tmp_path / "desk-kit"
    venv_bin = out / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    mill = venv_bin / "mill"
    mill.write_text("#!/bin/sh\n", encoding="utf-8")
    mill.chmod(0o755)
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(mill) if name == "mill" else None)
    assert mod.is_live_mill(out) is True
    with pytest.raises(SystemExit) as ei:
        mod.build_and_install(_fake_head(tmp_path), out)
    assert ei.value.code == 2


def test_refuse_replace_existing_venv_without_recreate(tmp_path: Path) -> None:
    mod = _mod()
    out = tmp_path / "kit"
    (out / "venv").mkdir(parents=True)
    with pytest.raises(SystemExit) as ei:
        mod.build_and_install(_fake_head(tmp_path), out, recreate=False)
    assert "refuse to replace" in str(ei.value)


def test_verdict_body_names_desks_and_rows() -> None:
    mod = _mod()
    body = mod.verdict_body(
        pr=999,
        head_sha="abc1234",
        join_sha="j" * 12,
        skill_sha="s" * 12,
        task_row="1/0/0/1s/1.4KB",
        join_row="9/0/0/31s",
        leave_row="1/0/0",
        verd="GREEN",
        opener="builder",
        partner="grok-tui",
    )
    assert "PR #999" in body
    assert "abc1234" in body
    assert "builder" in body and "grok-tui" in body and "validator" in body
    assert "task" in body.lower() and "1/0/0/1s/1.4KB" in body
    assert "join" in body.lower() and "leave" in body.lower()
    assert "GREEN" in body
    assert len(body) <= 2000


def test_verdict_rejects_bad_verd() -> None:
    mod = _mod()
    with pytest.raises(SystemExit):
        mod.verdict_body(
            pr=1,
            head_sha="a",
            join_sha="b",
            skill_sha="c",
            task_row="1",
            join_row="1",
            leave_row="1",
            verd="MAYBE",
            opener="builder",
            partner="grok-tui",
        )


def test_main_stage_only(tmp_path: Path, capsys) -> None:
    mod = _mod()
    head = _fake_head(tmp_path)
    out = tmp_path / "out"
    assert mod.main(["--root", str(head), "--out", str(out), "--stage-only", "--allow-dirty"]) == 0
    printed = capsys.readouterr().out
    assert "JOIN.md" in printed or "join_sha" in printed
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["join_sha"] and data["skill_sha"]
    assert "root" not in data
