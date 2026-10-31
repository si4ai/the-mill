"""#504 mill-wall auto-redact on write paths."""
from __future__ import annotations

import os

import pytest

from agent_coord.server.redact import PH, redact_text, scrub_request_body


def test_ssn_dashed():
    out, hits = redact_text("ssn is 123-45-6789 thanks")
    assert PH["ssn"] in out
    assert "123-45-6789" not in out
    assert "ssn" in hits


def test_pan_luhn_visa_test():
    # Visa test PAN 4111111111111111
    out, hits = redact_text("card 4111111111111111")
    assert PH["pan"] in out
    assert "4111111111111111" not in out
    assert "pan" in hits


def test_pan_fails_luhn_left_alone():
    out, hits = redact_text("id 4111111111111112")  # bad luhn
    assert "4111111111111112" in out
    assert "pan" not in hits


def test_bearer_token():
    tok = "Bearer " + "a" * 40
    out, hits = redact_text("auth " + tok)
    assert PH["token"] in out
    assert "a" * 20 not in out
    assert "token" in hits


def test_password_assignment():
    out, hits = redact_text("password=hunter2 end")
    assert PH["secret"] in out
    assert "hunter2" not in out
    assert "secret" in hits


def test_pem_block():
    pem = "-----BEGIN " + "PRIVATE KEY-----\\nabc\\n-----END " + "PRIVATE KEY-----"
    out, hits = redact_text("key:\\n" + pem)
    assert PH["pem"] in out
    assert "BEGIN PRIVATE KEY" not in out
    assert "pem" in hits


def test_iban():
    out, hits = redact_text("iban GB82WEST12345698765432")
    assert PH["bank"] in out
    assert "GB82WEST" not in out
    assert "bank" in hits


def test_desk_and_need_ids_not_redacted():
    s = "desk builder need remasure-0414 card 504"
    out, hits = redact_text(s)
    assert out == s
    assert hits == []


def test_disable_env(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_REDACT", "0")
    out, hits = redact_text("ssn 123-45-6789")
    assert "123-45-6789" in out
    assert hits == []


def test_scrub_request_body_send_note():
    body = {
        "verb": "send",
        "body": "leak 123-45-6789 and Bearer " + "x" * 32,
        "note": "password=secret",
        "detail": "ok",
    }
    hits = scrub_request_body(body)
    assert "ssn" in hits or "token" in hits or "secret" in hits
    assert "123-45-6789" not in body["body"]
    assert "password=secret" != body["note"] or PH["secret"] in body["note"]
    assert body.get("_redacted")
