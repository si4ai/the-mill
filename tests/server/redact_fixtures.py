# -*- coding: utf-8 -*-
"""Fake secret fixtures for the redactor, built at runtime from a seeded RNG.

Nothing here is a real credential, and no literal secret is stored in git:
every positive is a prefix plus random characters made when the module loads.
The 48 positives and 18 negatives are the 0.7.5 audit set (Redaction section).
"""
from __future__ import annotations

import base64
import random
import string


def build(seed: int = 7) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    R = random.Random(seed)

    def rs(n, alpha=string.ascii_letters + string.digits):
        return "".join(R.choice(alpha) for _ in range(n))

    UP = string.ascii_uppercase + string.digits
    b64u = string.ascii_letters + string.digits + "-_"
    jwt = "eyJ" + rs(30, b64u) + "." + "eyJ" + rs(40, b64u) + "." + rs(43, b64u)
    pem_body = "\n".join(rs(64, string.ascii_letters + string.digits + "+/") for _ in range(3))
    POS = [
     ("aws access key id", "AKIA" + rs(16, UP)),
     ("aws temp key id", "ASIA" + rs(16, UP)),
     ("aws secret (bare)", rs(40, string.ascii_letters + string.digits + "+/")),
     ("aws secret env", "AWS_SECRET_ACCESS_KEY=" + rs(40, string.ascii_letters + string.digits + "+/")),
     ("aws secret toml", 'aws_secret_access_key = "' + rs(40) + '"'),
     ("gitlab pat", "glpat-" + rs(20, b64u)),
     ("gitlab runner token", "glrt-" + rs(20, b64u)),
     ("github ghp", "ghp_" + rs(36)),
     ("github fine-grained", "github_pat_" + rs(22) + "_" + rs(59)),
     ("openai sk-", "sk-" + rs(48)),
     ("openai sk-proj-", "sk-proj-" + rs(64, b64u)),
     ("xai-", "xai-" + rs(64)),
     ("anthropic-style sk-ant-", "sk-ant-api03-" + rs(80, b64u)),
     ("slack bot", "xoxb-" + rs(11, string.digits) + "-" + rs(12, string.digits) + "-" + rs(24)),
     ("slack app-level xapp", "xapp-1-" + rs(11, UP) + "-" + rs(13, string.digits) + "-" + rs(64, "0123456789abcdef")),
     ("slack webhook url", "https://hooks.slack.com/services/T" + rs(8, UP) + "/B" + rs(8, UP) + "/" + rs(24)),
     ("jwt bare", jwt),
     ("pem rsa", "-----BEGIN " + "RSA PRIVATE KEY-----\n" + pem_body + "\n-----END " + "RSA PRIVATE KEY-----"),
     ("pem pkcs8", "-----BEGIN " + "PRIVATE KEY-----\n" + pem_body + "\n-----END " + "PRIVATE KEY-----"),
     ("pem encrypted", "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----\n" + pem_body + "\n-----END " + "ENCRYPTED PRIVATE KEY-----"),
     ("pem openssh", "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n" + pem_body + "\n-----END " + "OPENSSH PRIVATE KEY-----"),
     ("pem truncated (no END)", "-----BEGIN " + "PRIVATE KEY-----\n" + pem_body),
     ("bearer header", "Authorization: Bearer " + rs(32, b64u)),
     ("bearer short (16)", "Authorization: Bearer " + rs(16)),
     ("basic header", "Authorization: Basic " + base64.b64encode(b"svc:" + rs(14).encode()).decode()),
     ("private-token header", "PRIVATE-TOKEN: " + "glpat-" + rs(20, b64u)),
     ("url userinfo", "https://svc:" + rs(14) + "@git.example.com/a/b.git"),
     ("url token userinfo", "https://oauth2:" + "glpat-" + rs(20, b64u) + "@gitlab.example.com/x.git"),
     ("password= env", "DB_PASSWORD=" + rs(14)),
     ("password: yaml", "password: " + rs(14)),
     ("password json", '{"password": "' + rs(14) + '"}'),
     ("password toml", 'password = "' + rs(14) + '"'),
     ("token= env", "API_TOKEN=" + rs(32)),
     ("token json", '{"token": "' + rs(32) + '"}'),
     ("token toml", 'token = "' + rs(32) + '"'),
     ("secret toml", 'client_secret = "' + rs(32) + '"'),
     ("api_key json", '{"api_key":"' + rs(32) + '"}'),
     ("access_token qs", "https://x.example.com/cb?access_token=" + rs(32) + "&x=1"),
     ("mysql dsn", "mysql://mill:" + rs(14) + "@127.0.0.1:3306/agent_coord"),
     ("postgres dsn", "postgresql://app:" + rs(14) + "@db.internal:5432/app"),
     ("mongodb+srv", "mongodb+srv://u:" + rs(14) + "@c0.example.net/db"),
     ("mysql cli -p", "mysql -umill -p" + rs(14) + " agent_coord"),
     ("base64 of key=val", base64.b64encode(("password=" + rs(14)).encode()).decode()),
     ("generic high-entropy 64", rs(64, b64u)),
     ("stripe sk_live", "sk_live_" + rs(24)),
     ("google api key", "AIza" + rs(35, b64u)),
     ("npm token", "npm_" + rs(36)),
     ("pypi token", "pypi-AgEIcHlwaS5vcmc" + rs(60, b64u)),
    ]
    NEG = [
     ("git sha 40", rs(40, "0123456789abcdef")),
     ("git short sha", "fix in 6e6acda and 210f2a6"),
     ("sha256 hex", rs(64, "0123456789abcdef")),
     ("uuid", "3f2b8c1e-9a4d-4e2b-8f1a-2c3d4e5f6a7b"),
     ("python code password var", "password = get_password(cfg)"),
     ("python kwarg", "connect(password=s['password'], user=s['user'])"),
     ("prose 'token' word", "token: the push token rotates daily"),
     ("doc: secret=", "set secret=<redacted> in the box file"),
     ("card id list", "cards #201 #202 #203 and 9/12 done"),
     ("phone-ish 9 digits", "build 202610171 passed"),
     ("timestamp digits", "ts 1729212345678 ms"),
     ("long numeric id", "mail id 4111111111111111 in book"),  # luhn-valid test PAN
     ("IBAN-ish upper token", "AB12CDEFGHIJKLMNOP is a card slug"),
     ("account word", "account number: 12345678 rows scanned"),
     ("base64 png chunk", "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"),
     ("Bearer in prose", "the Bearer desk is the acting desk"),
     ("url no creds", "https://gitlab.com/group/project/-/merge_requests/12"),
     ("ssh fingerprint", "SHA256:" + rs(43, string.ascii_letters + string.digits + "+/")),
    ]
    return POS, NEG
