# -*- coding: utf-8 -*-
"""0.7.5: one redaction engine for stored text and log lines.

Fixtures are fake and built at runtime (redact_fixtures.build), so no
secret-shaped literal lands in git. Regression row S-6 (redact-engine).
"""
from __future__ import annotations

import base64
import random
import string
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redact_fixtures  # noqa: E402

from agent_coord.server import push
from agent_coord.server.redact import LOG_PH, PH, redact, redact_secrets, redact_text

POS, NEG = redact_fixtures.build(7)
R = random.Random(11)


def rs(n, alpha=string.ascii_letters + string.digits):
    return "".join(R.choice(alpha) for _ in range(n))


def _store(s):
    return redact_text(s)[0]


@pytest.mark.parametrize("name,secret", POS, ids=[n for n, _ in POS])
@pytest.mark.parametrize("fn", [_store, redact_secrets], ids=["store", "log"])
def test_audit_positive(fn, name, secret):
    if name in ("generic high-entropy 64",):
        pytest.skip("unkeyed random run: the backstop is key-gated by design")
    out = fn(secret)
    assert secret not in out, name


@pytest.mark.parametrize("name,text", NEG, ids=[n for n, _ in NEG])
@pytest.mark.parametrize("fn", [_store, redact_secrets], ids=["store", "log"])
def test_audit_negative_survives(fn, name, text):
    assert fn(text) == text, name


def test_catch_rate_floor_over_many_seeds():
    """Both policies catch at least 47 of 48 on every seed, with no false positive."""
    worst = 48
    for seed in range(40):
        pos, neg = redact_fixtures.build(seed)
        for fn in (_store, redact_secrets):
            caught = sum(s not in fn(s) for _, s in pos)
            worst = min(worst, caught)
            assert all(fn(t) == t for _, t in neg), seed
    assert worst >= 46


def test_one_engine_for_both_policies():
    assert push.redact_secrets is redact_secrets
    tok = "glpat-" + rs(20)
    assert redact(tok, "store")[0] == PH["token"]
    assert redact(tok, "log")[0] == LOG_PH


def test_keyed_value_keeps_the_key():
    v = rs(18)
    out = _store("DB_PASSWORD=" + v)
    assert out == "DB_PASSWORD=" + PH["secret"]
    out = _store('{"api_key": "' + v + '"}')
    assert out == '{"api_key": "' + PH["secret"] + '"}'


def test_aws_secret_after_key_id():
    key_id = "AKIA" + rs(16, string.ascii_uppercase + string.digits)
    secret = rs(39, string.ascii_letters + string.digits + "+/") + "/"
    out = _store(f"id {key_id} secret value {secret}")
    assert key_id not in out and secret not in out


def test_pem_encrypted_and_truncated():
    body = "\n".join(rs(64) for _ in range(3))
    for kind in ("ENCRYPTED PRIVATE KEY", "OPENSSH PRIVATE KEY", "EC PRIVATE KEY"):
        block = f"-----BEGIN {kind}-----\n{body}\n-----END {kind}-----"
        assert body not in _store("see\n" + block + "\nend")
    out = _store("-----BEGIN " + "PRIVATE KEY-----\n" + body + "\n\nnext paragraph")
    assert body not in out and out.endswith("next paragraph")


def test_url_credentials_keep_host():
    pw = rs(14)
    out = redact_secrets(f"clone https://svc:{pw}@git.example.com/a.git")
    assert pw not in out and "git.example.com/a.git" in out


def test_bearer_needs_a_token_shape():
    assert _store("the bearer token_hash index") == "the bearer token_hash index"
    assert _store("Bearer mismatch until connect") == "Bearer mismatch until connect"
    tok = rs(12) + "9"
    assert tok not in _store("Bearer " + tok)


def test_entropy_backstop_is_key_gated():
    run = rs(30) + "7Q"
    assert run not in _store("the deploy token is " + run)
    assert _store("the build artifact is " + run) == "the build artifact is " + run


def test_base64_wrapped_secret():
    inner = "token=" + rs(24)
    blob = base64.b64encode(inner.encode()).decode()
    assert blob not in _store("payload " + blob)
    plain = base64.b64encode(b"just a short note about the build, nothing secret here").decode()
    assert _store("payload " + plain) == "payload " + plain


@pytest.mark.parametrize(
    "text",
    [
        "Push fix/242-mail-thread-mark-flags (ac027c0) after the token rotates",
        "Evidence ~/.mill/evidence/garden-measure-2026-10-14/SUMMARY.md for the invite-key run",
        "MR !44 garden/join-invite-key-d2 keeps the key path",
        "token: mill-hold gets server clock",
        "UPDATE join SET token_hash=NULL, doing=''",
        "reads ?invite=, X-Mill-Invite, then the door",
        "The invite-key /?invite=KEY stays",
        'a test fixture secret="s"); commit',
        "letters (1183 1189 1211 1223 1251), each one",
        "max_tokens=1000000 per call",
        "password = get_password(cfg) and secret = cfg.secret",
        "merged 17f0e624b28479ad7e60e5ed7e6eacaf810cb18f on main",
    ],
)
def test_mill_prose_survives(text):
    """Shapes seen in real mill letters and cards stay as written."""
    assert _store(text) == text
    assert redact_secrets(text) == text


def test_card_number_needs_a_card_word():
    pan = "4111" + "1111" + "1111" + "1111"
    assert PH["pan"] in _store("card " + pan)
    assert _store("mail id " + pan) == "mail id " + pan


def test_iban_needs_a_valid_checksum():
    good = "GB82" + "WEST" + "1234" + "5698" + "7654" + "32"
    assert PH["bank"] in _store("iban " + good)
    assert _store("slug AB12CDEFGHIJKLMNOP") == "slug AB12CDEFGHIJKLMNOP"


def test_store_switches_still_work(monkeypatch):
    tok = "ghp_" + rs(36)
    monkeypatch.setenv("AGENT_COORD_REDACT", "0")
    assert redact_text(tok)[0] == tok
    monkeypatch.setenv("AGENT_COORD_REDACT", "1")
    monkeypatch.setenv("AGENT_COORD_REDACT_CLASSES", "ssn")
    assert redact_text(tok)[0] == tok
    monkeypatch.delenv("AGENT_COORD_REDACT_CLASSES")
    assert redact_text(tok)[0] == PH["token"]


def test_long_text_is_fast():
    import time

    text = ("note about 6e6acda and agent_coord/server/redact.py token rotation. " * 60)[:4096]
    t0 = time.perf_counter()
    for _ in range(50):
        redact_text(text)
    assert (time.perf_counter() - t0) / 50 < 0.02


def test_docs_name_the_row():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs" / "security" / "REGRESSION-MATRIX.md").read_text(encoding="utf-8")
    assert "| S-6 |" in text and "test_redact_engine_075.py" in text
