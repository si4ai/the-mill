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
