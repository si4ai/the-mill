"""One secret redactor for the mill wall: stored text and log lines (#504, 0.7.5).

Best effort. It narrows what an agent can leak into a letter, card, note,
score or log; it cannot catch every secret. The standing rule still holds:
reference a file path, never paste the value.

One ordered rule list, two policies:
  store  -> [REDACTED:CLASS] placeholders, used before a write is stored
  log    -> [redacted], used on log lines, hint files and glance fields

Rules, in order: private key blocks, URL credentials, auth headers, token
families with a fixed prefix, keyed values (password=, "token": ...), door
query keys, a key-gated entropy backstop, a base64 rescan, then the PII
classes (ssn, pan, bank). Hex digests, git shas and UUIDs are never touched.

Env (store policy only):
  AGENT_COORD_REDACT=0|off|false|no  - disable
  AGENT_COORD_REDACT_CLASSES=ssn,pan,... - subset (default all)
"""
from __future__ import annotations

import base64
import binascii
import math
import os
import re
from collections import Counter
from typing import Any, Callable

PH = {
    "ssn": "[REDACTED:SSN]",
    "pan": "[REDACTED:PAN]",
    "secret": "[REDACTED:SECRET]",
    "token": "[REDACTED:TOKEN]",
    "pem": "[REDACTED:PEM]",
    "bank": "[REDACTED:BANK]",
}
LOG_PH = "[redacted]"

ALL_CLASSES = frozenset(PH)

# Every command that stores text a reader will see (0.7.5: reply, doing, join,
# claim, unclaim, pass, hold and assign joined send, note, open and score).
WRITE_COMMANDS = frozenset({
    "send", "reply", "note", "create", "open", "update", "score", "patch", "set",
    "join", "claim", "unclaim", "pass", "hold", "assign",
    # #818 PR B: --doing text rides on these too.
    "mark", "drop", "unpark",
})

TEXT_KEYS = frozenset({
    "body", "note", "detail", "doing", "msg", "message", "text",
    "title", "summary", "content", "description", "comment",
    "value", "target",
})

# shortest keyed value each policy redacts: a log line has no reader who needs
# the value, so it redacts shorter ones than stored text does.
_MIN_VALUE = {"store": 6, "log": 4}


def _enabled() -> bool:
    v = (os.environ.get("AGENT_COORD_REDACT") or "1").strip().lower()
    return v not in ("0", "off", "false", "no")


def _classes() -> frozenset[str]:
    raw = (os.environ.get("AGENT_COORD_REDACT_CLASSES") or "").strip()
    if not raw:
        return ALL_CLASSES
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip()) & ALL_CLASSES


# --- rules -------------------------------------------------------------------

_PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
    r".*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\n[ \t]*\n|\Z)",
    re.S,
)
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,20}://)[^/\s:@]+:[^/\s@]+@")
_AUTH_HEADER = re.compile(
    r"(?i)\b((?:proxy-)?authorization\s*[:=]\s*(?:(?:bearer|basic|token|digest|negotiate)\s+)?)"
    r"([^\s\"',;]+)"
)
_NAMED_HEADER = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])((?:x-mill-invite|x-mill-directory|private-token|job-token|x-api-key|x-auth-token|"
    r"factory-door|directory_client_secret|client_secret|set-cookie|cookie)\s*[:=]\s*)([^\s\"',;]+)"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)((?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{8,}|[A-Za-z0-9._~+/=-]{24,})")

# Token families with a fixed prefix. Each is long and specific enough to be
# redacted wherever it stands.
_FAMILIES = (
    r"gl(?:pat|rt|ptt|dt|soat|cbt|imt|ft|agent|oas|rtr)-[A-Za-z0-9_-]{20,}",
    r"(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16}",
    r"sk-(?:proj-|ant-[a-z0-9]{2,8}-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
    r"[sr]k_(?:live|test)_[A-Za-z0-9]{16,}",
    r"xai-[A-Za-z0-9_-]{20,}",
    r"crsr_[A-Za-z0-9]{32,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"xox[a-z]-[A-Za-z0-9-]{10,}",
    r"xapp-[A-Za-z0-9-]{10,}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"npm_[A-Za-z0-9]{36}",
    r"pypi-AgE[A-Za-z0-9_-]{50,}",
    r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
)
_FAMILY = re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(_FAMILIES) + r")(?![A-Za-z0-9_-])")
_HOOK_URL = re.compile(r"(?i)https://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_-]+")

_SECRET_KEY = (
    r"[A-Za-z0-9_.-]*?(?:password|passwd|passphrase|pwd|secret|token|api[_-]?key|apikey|"
    r"access[_-]?key|private[_-]?key|credentials?|signature|session[_-]?key)"
)
_KEYED = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])([\"']?" + _SECRET_KEY + r"[\"']?(\s*[:=]\s*))"
    r"(?:\"([^\"\n]*)\"|'([^'\n]*)'|([^\s\"'&,;()\[\]{}<>]+))"
)
_DOOR_QS = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])((?:invite|invite_key|seat|code|pem|token_hash)=)([^\s\"'&,;()\[\]{}<>]+)"
)
_MYSQL_P = re.compile(r"(?i)\b((?:mysql|mysqldump|mariadb|mysqladmin)\b[^\n]*?\s-p)(\S+)")
_AWS_SECRET_NEAR_ID = re.compile(
    r"(?<![A-Za-z0-9_-])((?:AKIA|ASIA)[A-Z0-9]{16}|\[REDACTED:TOKEN\]|\[redacted\])"
    r"([^\n]{1,80}?)(?<![A-Za-z0-9/+=])([A-Za-z0-9/+]{40})(?![A-Za-z0-9/+=])"
)

# Key-gated entropy backstop: a long random-looking run soon after a
# secret-ish word on the same line.
_GATE_WORD = re.compile(
    r"(?i)\b(?:secret|secrets|token|tokens|password|passwd|passphrase|api[ _-]?key|apikey|"
    r"access[ _-]?key|private[ _-]?key|key|credential|credentials|bearer|auth|signature)\b"
)
_RUN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{20,}={0,2}(?![A-Za-z0-9+/=_-])")
_HEX = re.compile(r"[0-9a-fA-F]+")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_GATE_SPAN = 48
_ENTROPY_MIN = 3.5
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=_-])")
_B64_MAX_RUNS = 32

_SSN = re.compile(r"(?<!\d)(\d{3}-\d{2}-\d{4})(?!\d)")
_PAN = re.compile(r"(?<![\d-])(\d(?:[ -]?\d){12,18})(?![\d-])")
_PAN_WORD = re.compile(r"(?i)\b(?:card|visa|mastercard|amex|discover|pan|cc|credit|debit)\b")
_IBAN = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b")
_ROUTING_ACCT = re.compile(
    r"(?i)\b(?:routing|account|acct)\s*(?:number|#|no\.?)\s*[:=]?\s*(\d{9,17})\b"
)

_PLACEHOLDER = re.compile(
    r"(?i)^(?:<.*>?|\[redacted.*|\$\{?.*|%\(?.*|\{\{.*|\*+|x{3,}|\.\.\.+|none|null|nil|true|false|"
    r"undefined|redacted|changeme|example|placeholder)$"
)
_IDENT_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _entropy(s: str) -> float:
    n = len(s)
    if not n:
        return 0.0
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _is_digest(s: str) -> bool:
    """Hex digests, git shas and UUIDs are ordinary in mill text."""
    core = s.rstrip("=")
    return bool(_HEX.fullmatch(core) or _UUID.fullmatch(core))


_PATHLIKE = re.compile(r"[a-z0-9_.-]+(?:/[a-z0-9_.-]+){2,}/?")
_WORD_SEG = re.compile(r"[a-z]+\d*|[A-Z]+\d*|[A-Z][a-z]+\d*|\d+")


def _wordy(s: str) -> bool:
    """A slug, branch or path made of words and numbers (fix/242-mail-thread)."""
    segs = [x for x in re.split(r"[-_/.+=]", s) if x]
    return len(segs) >= 2 and all(_WORD_SEG.fullmatch(x) for x in segs)
_FINGERPRINT_TAIL = ("SHA256:", "SHA512:", "SHA1:", "MD5:")


def _random_looking(s: str) -> bool:
    if _is_digest(s) or _PATHLIKE.fullmatch(s) or _wordy(s):
        return False
    core = s.rstrip("=")
    kinds = sum((any(c.islower() for c in core), any(c.isupper() for c in core), any(c.isdigit() for c in core)))
    return kinds >= 2 and any(c.isdigit() for c in core) and _entropy(core) >= _ENTROPY_MIN


def _keep_value(value: str, sep: str, policy: str, quoted: bool, key: str = "", after: str = "") -> bool:
    """True when a keyed value is plainly not a secret (code, placeholder, prose, count)."""
    v = value.strip()
    if len(v) < _MIN_VALUE[policy]:
        return True
    if _PLACEHOLDER.match(v) or _IDENT_PATH.match(v) or re.fullmatch(r"[A-Z][A-Z_]{1,15}", v):
        return True
    if not quoted and after[:1] in ("(", "[", "."):
        return True  # password = get_password(cfg), s['password'], cfg.secret
    if v.isdigit() and re.search(r"(?i)(?:tokens?|keys?)[\"']?$", key.split(":")[0].split("=")[0].strip()):
        return True  # max_tokens=1000000 is a count
    if not quoted and ":" in sep and "=" not in sep and re.fullmatch(r"[a-z]+(?:[-_][a-z]+)*", v):
        return True  # "token: mill-hold gets" is prose, not a value
    return False


def _luhn_ok(digits: str) -> bool:
    s = 0
    alt = False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return s % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw[4:] + raw[:4]
    digits = "".join(str(int(ch, 36)) for ch in s)
    return int(digits) % 97 == 1


class _Pass:
    """One redaction pass over a text: placeholder per class, hits in order."""

    def __init__(self, policy: str, classes: frozenset[str]):
        self.policy = policy
        self.classes = classes
        self.hits: list[str] = []

    def ph(self, cls: str) -> str:
        if cls not in self.hits:
            self.hits.append(cls)
        return PH[cls] if self.policy == "store" else LOG_PH

    def sub(self, rx: re.Pattern[str], cls: str, text: str, keep: int | None = None) -> str:
        """Replace each match; keep=N keeps group N (a key or header name) in front."""
        if cls not in self.classes:
            return text

        def rep(m: re.Match[str]) -> str:
            head = m.group(keep) if keep else ""
            return head + self.ph(cls)

        return rx.sub(rep, text)


def _keyed(p: _Pass, text: str) -> str:
    if "secret" not in p.classes:
        return text

    def rep(m: re.Match[str]) -> str:
        head, sep = m.group(1), m.group(2)
        if m.group(3) is not None:
            val, q = m.group(3), '"'
        elif m.group(4) is not None:
            val, q = m.group(4), "'"
        else:
            val, q = m.group(5), ""
        after = m.string[m.end(): m.end() + 1]
        if _keep_value(val, sep, p.policy, bool(q), key=head, after=after):
            return m.group(0)
        return head + q + p.ph("secret") + q

    return _KEYED.sub(rep, text)


def _door(p: _Pass, text: str) -> str:
    if "secret" not in p.classes:
        return text

    def rep(m: re.Match[str]) -> str:
        if _keep_value(m.group(2), "=", p.policy, True):
            return m.group(0)
        return m.group(1) + p.ph("secret")

    return _DOOR_QS.sub(rep, text)


def _aws_secret(p: _Pass, text: str) -> str:
    """A 40-char key after an access key id, and a bare 40-char mixed run."""
    if "token" not in p.classes:
        return text
    text = _AWS_SECRET_NEAR_ID.sub(lambda m: m.group(1) + m.group(2) + p.ph("token"), text)

    def bare(m: re.Match[str]) -> str:
        s = m.group(0)
        if (
            len(s) == 40
            and "_" not in s
            and "-" not in s
            and s.count("/") <= 4
            and any(c.isupper() for c in s)
            and any(c.islower() for c in s)
            and _random_looking(s)
            and _entropy(s) >= 4.5
            and not m.string[max(0, m.start() - 7): m.start()].upper().endswith(_FINGERPRINT_TAIL)
        ):
            return p.ph("token")
        return s

    return _RUN.sub(bare, text)


def _entropy_backstop(p: _Pass, text: str) -> str:
    if "secret" not in p.classes:
        return text
    out: list[str] = []
    last = 0
    for line_m in re.finditer(r"[^\n]+", text):
        line = line_m.group(0)
        gates = [g.end() for g in _GATE_WORD.finditer(line)]
        if not gates:
            continue
        for m in _RUN.finditer(line):
            if not any(0 <= m.start() - g <= _GATE_SPAN for g in gates):
                continue
            if not _random_looking(m.group(0)) or len(m.group(0).rstrip("=")) < 20:
                continue
            if line[max(0, m.start() - 7): m.start()].upper().endswith(_FINGERPRINT_TAIL):
                continue
            a, b = line_m.start() + m.start(), line_m.start() + m.end()
            out.append(text[last:a])
            out.append(p.ph("secret"))
            last = b
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


def _decoded_text(run: str) -> str:
    raw = run.rstrip("=")
    try:
        data = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True)
    except (binascii.Error, ValueError):
        return ""
    if len(data) < 8:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    printable = sum(ch.isprintable() or ch in "\n\r\t" for ch in text)
    return text if printable >= 0.9 * len(text) else ""


def _base64_rescan(p: _Pass, text: str) -> str:
    """Redact a base64 run whose decoded text holds a secret (a hidden key=value)."""
    if not ({"secret", "token", "pem"} & p.classes):
        return text
    seen = 0

    def rep(m: re.Match[str]) -> str:
        nonlocal seen
        run = m.group(0)
        if _is_digest(run):
            return run
        seen += 1
        if seen > _B64_MAX_RUNS:
            return run
        inner = _decoded_text(run)
        if not inner:
            return run
        probe = _Pass(p.policy, p.classes)
        if _secret_rules(probe, inner) == inner:
            return run
        return p.ph(probe.hits[0])

    return _B64_RUN.sub(rep, text)


def _secret_rules(p: _Pass, text: str) -> str:
    text = p.sub(_PEM, "pem", text)
    text = p.sub(_USERINFO, "secret", text, keep=1)
    text = p.sub(_AUTH_HEADER, "token", text, keep=1)
    text = p.sub(_NAMED_HEADER, "secret", text, keep=1)
    text = p.sub(_HOOK_URL, "token", text)
    text = p.sub(_FAMILY, "token", text)
    text = p.sub(_BEARER, "token", text, keep=1)
    text = p.sub(_MYSQL_P, "secret", text, keep=1)
    text = _keyed(p, text)
    text = _door(p, text)
    text = _aws_secret(p, text)
    return _entropy_backstop(p, text)


def _pii_rules(p: _Pass, text: str) -> str:
    text = p.sub(_SSN, "ssn", text)
    if "pan" in p.classes:
        def pan(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group(1))
            near = _PAN_WORD.search(text[max(0, m.start() - 32): m.start()])
            if 13 <= len(digits) <= 19 and _luhn_ok(digits) and near:
                return p.ph("pan")
            return m.group(0)

        text = _PAN.sub(pan, text)
    if "bank" in p.classes:
        text = _IBAN.sub(lambda m: p.ph("bank") if _iban_ok(m.group(1)) else m.group(0), text)
        text = _ROUTING_ACCT.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + p.ph("bank"), text)
    return text


def redact(text: str, policy: str = "store", classes: frozenset[str] | None = None) -> tuple[str, list[str]]:
    """Redact text under one policy. Returns (text, classes hit in order)."""
    if not text:
        return text, []
    use = ALL_CLASSES if classes is None else classes
    p = _Pass(policy, use)
    out = _secret_rules(p, text)
    out = _base64_rescan(p, out)
    if policy == "store":
        out = _pii_rules(p, out)
    return out, p.hits


# --- store policy --------------------------------------------------------------

def redact_text(text: str, classes: frozenset[str] | None = None) -> tuple[str, list[str]]:
    """Store policy: [REDACTED:CLASS] placeholders. Honors the env switches."""
    if not text or not _enabled():
        return text, []
    use = classes if classes is not None else _classes()
    if not use:
        return text, []
    return redact(text, "store", use)


def scrub_request_body(body: dict[str, Any], classes: frozenset[str] | None = None) -> list[str]:
    if not isinstance(body, dict) or not _enabled():
        return []
    use = classes if classes is not None else _classes()
    all_hits: list[str] = []
    for key in list(body.keys()):
        if key not in TEXT_KEYS:
            continue
        val = body.get(key)
        if not isinstance(val, str) or not val:
            continue
        new, hits = redact_text(val, use)
        if hits:
            body[key] = new
            for h in hits:
                if h not in all_hits:
                    all_hits.append(h)
    if all_hits:
        body["_redacted"] = list(all_hits)
    return all_hits


def err_text(e: BaseException, limit: int = 240) -> str:
    """Exception text for a reply or an alert: redacted, then cut."""
    return redact_secrets(str(e))[:limit]


# --- log policy ----------------------------------------------------------------

def redact_secrets(msg: str) -> str:
    """Log policy: strip secrets before any wall log line or glance field is stored."""
    return redact(msg or "", "log")[0]


def redact_format(msg: str, *args: Any) -> str:
    """Format a log line, then strip secrets. For loggers that do not use dest_log."""
    try:
        text = msg % args if args else msg
    except Exception:
        text = msg
    return redact_secrets(text)


def redact_obj(value: Any, fn: Callable[[str], str] = redact_secrets) -> Any:
    """Redact secret strings anywhere in a frame before it is written to a log file."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: redact_obj(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v, fn) for v in value]
    return value
