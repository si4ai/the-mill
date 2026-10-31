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
    sk = _j("sk-", "abcdefghijklmnopqrstuvwxyz12")
    assign = _j("const API_", "TOKEN", " = '", "Aa1" * 12, "'")
    for text, kind in (
        (aws_id, "aws-access-key-id"),
        (f"{aws_id} {aws_secret}", "aws-secret-access-key"),
        (f"key={aws_id}", "aws-access-key-id"),
        (ghp, "github-pat"),
        (pypi, "pypi-token"),
        (pem + "\nabc\n-----END OPENSSH PRIVATE KEY-----", "pem-private-key"),
        (xox, "slack-token"),
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
