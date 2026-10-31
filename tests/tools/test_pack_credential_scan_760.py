"""F206 (#760): check_pack refuses credential shapes in tip and pack.

Canaries are assembled at run time so this file stays clean under the tip scan.
Documented vectors pass only via the exact-value allow-list.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("check_pack_760", ROOT / "tools" / "check_pack.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _j(*parts: str) -> str:
    return "".join(parts)


def test_canary_shapes_fail() -> None:
    mod = _mod()
    aws_id = _j("AKIA", "IOSFODNN7", "EXAMPLE")
    aws_secret = _j("wJalrXUtnFEMI/K7MDENG/bPxRfiCY", "EXAMPLEKEY")
    ghp = _j("ghp_", "A" * 36)
    pypi = _j("pypi-AgEIcHlwaS5vcmcB", "B" * 50)
    pem = _j("-----BEGIN ", "OPENSSH PRIVATE KEY-----")
    xox = _j("xoxb-", "1234567890-abcdefghijklmnop")
    xoxa = _j("xoxa-", "2-2345678901-AbCdEfGhIjKlMnOp")
    xoxp = _j("xoxp-", "2345678901-2345678901-AbCdEfGhIjKlMnOp")
    gpat = _j("github_pat_", "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ")
    asia = _j("ASIA", "IOSFODNN7", "EXAMPLE")
    sk = _j("sk-", "abcdefghijklmnopqrstuvwxyz12")
    assign = _j("const API_", "TOKEN", " = '", "Aa1" * 12, "'")
    for text, kind in (
        (aws_id, "aws-access-key-id"),
        (asia, "aws-access-key-id"),
        (f"{aws_id} {aws_secret}", "aws-secret-access-key"),
        (f"key={aws_id}", "aws-access-key-id"),
        (ghp, "github-pat"),
        (gpat, "github-pat"),
        (pypi, "pypi-token"),
        (pem + "\nabc\n-----END OPENSSH PRIVATE KEY-----", "pem-private-key"),
        (xox, "slack-token"),
        (xoxa, "slack-token"),
        (xoxp, "slack-token"),
        (sk, "sk-api-key"),
        (assign, "high-entropy-secret-assign"),
    ):
        kinds = mod.credential_kinds(text)
        assert kind in kinds, (text[:20], kinds)


def test_allowlisted_exact_vector_passes() -> None:
    mod = _mod()
    # A documented vector on the allow-list must be exact; a near miss still fails.
    allowed = next(iter(mod.CREDENTIAL_ALLOWLIST))
    assert mod.credential_kinds(allowed) == []
    near = "ghp_" + "B" * 36
    assert near != allowed
    assert "github-pat" in mod.credential_kinds(near)
    # Sharing the first 8 characters is not enough (exact match only).
    prefix_near = allowed[:8] + ("D" * (len(allowed) - 8))
    assert prefix_near != allowed
    assert "github-pat" in mod.credential_kinds(prefix_near)


def test_clean_text_passes() -> None:
    mod = _mod()
    for text in (
        "const tip = 'hello'",
        "AKIA is a prefix we mention in docs without the rest",
        "use an API TOKEN name in prose",
        "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
        "",
    ):
        assert mod.credential_kinds(text) == [], text


def test_k7_assignment_shapes() -> None:
    """JSON, unquoted YAML/.env/export/INI, and hex40/hex64 must fail (K7)."""
    mod = _mod()
    secret = _j("Zx9/Kq2LmN8pR4sT6vW1yZ3aB5cD7eF0gH2iJ4k", "L")
    hex40 = "3f9a" * 10
    hex64 = "9c1e" * 16
    cases = (
        ('"client_secret": "' + secret + '"', "high-entropy-secret-assign"),
        ("client_secret: " + secret, "high-entropy-secret-assign"),
        ("GITHUB_TOKEN=" + secret, "high-entropy-secret-assign"),
        ("export MY_SECRET=" + secret, "high-entropy-secret-assign"),
        ("aws_secret_access_key = " + secret, "high-entropy-secret-assign"),
        ('API_KEY = "' + hex40 + '"', "high-entropy-secret-assign"),
        ('WEBHOOK_SECRET = "' + hex64 + '"', "high-entropy-secret-assign"),
        # Bare KEY/TOKEN/SECRET names (no prefix before the keyword).
        ("TOKEN=" + secret, "high-entropy-secret-assign"),
        ("secret: " + secret, "high-entropy-secret-assign"),
        ('key = "' + secret + '"', "high-entropy-secret-assign"),
        ('"token": "' + secret + '"', "high-entropy-secret-assign"),
    )
    for text, kind in cases:
        kinds = mod.credential_kinds(text)
        assert kind in kinds, (text[:40], kinds)


def test_precommit_msg_rejects_github_pat(tmp_path) -> None:
    """precommit_hygiene msg must fail on a ghp_ token in the commit message."""
    import subprocess
    import sys

    ghp = _j("ghp_", "A" * 36)
    msg = tmp_path / "COMMIT_MSG"
    msg.write_text(_j("card 760: seed ", ghp, "\n"), encoding="utf-8")
    got = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "precommit_hygiene.py"), "msg", str(msg)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert got.returncode == 1, got.stdout + got.stderr
    assert "credential" in (got.stderr + got.stdout).lower()


def _fresh_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q"], cwd=repo)
    subprocess.check_call(["git", "config", "user.email", "builder@users.noreply.github.com"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "builder"], cwd=repo)
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "README.md"], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "--no-verify", "-m", "seed"], cwd=repo)
    return repo


def test_scan_git_tracked_flags_credential(tmp_path, monkeypatch) -> None:
    """Tip scan reports credential shapes (kills the no-git-tip-hook mutant)."""
    import subprocess

    mod = _mod()
    repo = _fresh_repo(tmp_path)
    ghp = _j("ghp_", "A" * 36)
    (repo / "note.txt").write_text(_j("seed ", ghp, "\n"), encoding="utf-8")
    subprocess.check_call(["git", "add", "note.txt"], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "--no-verify", "-m", "add note"], cwd=repo)
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    fails = mod.scan_git_tracked(())
    assert any("credential shape" in f and "git tip" in f for f in fails), fails


def test_scan_artifact_flags_credential(tmp_path) -> None:
    """Pack member scan reports credential shapes (kills the no-artifact-hook mutant)."""
    import io
    import tarfile
    import zipfile

    mod = _mod()
    ghp = _j("ghp_", "A" * 36)
    payload = _j("seed ", ghp, "\n").encode()
    whl = tmp_path / "the_mill-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("agent_coord/zz.py", payload)
    fails, _notes = mod.scan_artifact(whl, "wheel")
    assert any("credential shape" in f for f in fails), fails
    sdist = tmp_path / "the_mill-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as tf:
        info = tarfile.TarInfo(name="the_mill-0.0.0/agent_coord/zz.py")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    fails, _notes = mod.scan_artifact(sdist, "sdist")
    assert any("credential shape" in f for f in fails), fails


def test_scan_git_messages_flags_credential(tmp_path, monkeypatch) -> None:
    """Commit-message scan reports credential shapes (N5)."""
    import subprocess

    mod = _mod()
    repo = _fresh_repo(tmp_path)
    ghp = _j("ghp_", "A" * 36)
    subprocess.check_call(
        ["git", "commit", "-q", "--allow-empty", "--no-verify", "-m", _j("card 760 seed ", ghp)],
        cwd=repo,
    )
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    fails = mod.scan_git_messages()
    assert any("credential shape" in f and "git commit" in f for f in fails), fails


def test_scan_head_message_flags_credential(tmp_path, monkeypatch) -> None:
    """--head-message / scan_head_message reports credential shapes (N6)."""
    import subprocess

    mod = _mod()
    repo = _fresh_repo(tmp_path)
    ghp = _j("ghp_", "A" * 36)
    subprocess.check_call(
        ["git", "commit", "-q", "--allow-empty", "--no-verify", "-m", _j("card 760 seed ", ghp)],
        cwd=repo,
    )
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    fails = mod.scan_head_message()
    assert any("credential shape" in f for f in fails), fails


def test_precommit_tree_and_staged_flag_credential(tmp_path, monkeypatch) -> None:
    """precommit_hygiene tree and staged paths report credential shapes (M6/M7)."""
    import importlib.util
    import subprocess
    import sys

    repo = _fresh_repo(tmp_path)
    ghp = _j("ghp_", "A" * 36)
    (repo / "tools").mkdir()
    # Copy hygiene + check_pack into the temp repo so ROOT resolves there.
    import shutil

    shutil.copy(ROOT / "tools" / "precommit_hygiene.py", repo / "tools" / "precommit_hygiene.py")
    shutil.copy(ROOT / "tools" / "check_pack.py", repo / "tools" / "check_pack.py")
    # Minimal hygiene_words so ordinary_words works
    (repo / "tools" / "hygiene_words.txt").write_text("the\na\n", encoding="utf-8")
    (repo / "canary.txt").write_text(_j("seed ", ghp, "\n"), encoding="utf-8")
    subprocess.check_call(["git", "add", "canary.txt", "tools"], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "--no-verify", "-m", "canary"], cwd=repo)
    spec = importlib.util.spec_from_file_location("hyg_760", repo / "tools" / "precommit_hygiene.py")
    hyg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Ensure import finds check_pack next to it
    sys.path.insert(0, str(repo / "tools"))
    try:
        spec.loader.exec_module(hyg)
        tree_fails = hyg.scan_tree()
        assert any("credential shape" in f for f in tree_fails), tree_fails
        # Staged: modify and stage another canary
        (repo / "staged.txt").write_text(_j("seed ", ghp, "\n"), encoding="utf-8")
        subprocess.check_call(["git", "add", "staged.txt"], cwd=repo)
        staged_fails = hyg.scan_staged()
        assert any("credential shape" in f for f in staged_fails), staged_fails
    finally:
        sys.path.pop(0)
