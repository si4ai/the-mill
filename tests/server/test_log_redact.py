"""Wall log files must not keep a bearer, an invite, or any other door secret.

The hygiene check looks at source shape. Its regression plants a log call that
interpolates a variable named token. That fixture has no home path, no address,
and no real secret. The file check writes made-up values through the real
writers and reads the temporary log files back.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from agent_coord.server.asgi import _line, record_access
from agent_coord.server.push import api_log, dest_log, perf_log
from agent_coord.server.redact import redact_format, redact_obj, redact_secrets

_LOG_FUNCS = frozenset({"api_log", "perf_log", "dest_log", "_bc_log", "mill_admin_alert"})
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})
_LOGGER_NAMES = frozenset({"_log", "log", "logger"})
_SECRET_IDS = frozenset(
    {
        "token",
        "bearer",
        "invite",
        "secret",
        "authorization",
        "password",
        "client_secret",
        "directory_token",
        "access_token",
        "id_token",
        "invite_key",
        "raw_token",
    }
)
_WRITER_FUNCS = frozenset({"dest_log", "record_access"})
_LOG_FILENAMES = (
    "mill-api.log",
    "mill-perf.log",
    "mill-backchannel.log",
    "mill-wall-access.log",
)
_WRITER_NAMES = _SECRET_IDS | {"msg", "path", "query", "headers", "body"}
_PERSONAL = re.compile(
    r"@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|[A-Za-z]:\\Users\\"
    r"|/home/"
    r"|/Users/"
    r"|(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"
)


def _callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id in _LOG_FUNCS:
        return True
    if isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:
        base = func.value
        if isinstance(base, ast.Name) and (base.id in _LOGGER_NAMES or base.id.endswith("_log")):
            return True
    return False


def _is_write_call(node: ast.Call) -> bool:
    return _callee(node) == "write"


def _expr_is_redact(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _callee(node) == "redact_secrets":
        return True
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in {"rstrip", "strip", "lstrip"}:
        return _expr_is_redact(func.value)
    return False


def _assigned_from_redact(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _expr_is_redact(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _mentions_log_file(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(name in node.value for name in _LOG_FILENAMES):
                return True
    return False


def _named_loads(node: ast.AST, names: set[str], redacted: set[str]) -> list[str]:
    found: list[str] = []

    def walk(current: ast.AST) -> None:
        if isinstance(current, ast.Call) and _callee(current) == "redact_secrets":
            return
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            if current.id in names and current.id not in redacted:
                found.append(current.id)
        elif isinstance(current, ast.Attribute) and current.attr in names:
            found.append(current.attr)
        elif isinstance(current, ast.keyword) and current.arg in names:
            found.append(current.arg)
        for child in ast.iter_child_nodes(current):
            walk(child)

    walk(node)
    return found


def _is_writer(fn: ast.AST) -> bool:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if fn.name in _WRITER_FUNCS:
        return True
    if not _mentions_log_file(fn):
        return False
    return any(isinstance(node, ast.Call) and _is_write_call(node) for node in ast.walk(fn))


def findings_in_source(source: str, filename: str) -> list[str]:
    """Log calls that interpolate a secret name, and log writers that skip redact."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"{filename}: could not parse"]
    found: list[str] = []
    writers = [node for node in ast.walk(tree) if _is_writer(node)]
    writer_ids = {id(node) for node in writers}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_logger_call(node):
            for name in _named_loads(node, _SECRET_IDS | {"query"}, set()):
                found.append(f"{filename}:{node.lineno} log interpolates {name}")
        if id(node) in writer_ids:
            redacted = _assigned_from_redact(node)
            if not redacted:
                found.append(f"{filename}:{node.lineno} {node.name} does not call redact_secrets")
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if not (_is_write_call(call) or _is_logger_call(call)):
                    continue
                for name in _named_loads(call, _WRITER_NAMES, redacted):
                    found.append(f"{filename}:{call.lineno} {node.name} writes {name}")
    return found


def scan_agent_coord(root: Path | None = None) -> list[str]:
    repo = root or Path(__file__).resolve().parents[2]
    found: list[str] = []
    for path in sorted((repo / "agent_coord").rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        found.extend(findings_in_source(path.read_text(encoding="utf-8"), rel))
    return found


def test_access_line_hides_invite_query():
    secret = "invite-plain-secret"
    line = redact_secrets(_line("GET", "/?invite=" + secret, 200, 1.0, 10))
    assert secret not in line
    assert "invite=[redacted]" in line


def test_log_hides_bearer_and_directory_header():
    bearer = "desk-bearer-secret"
    directory = "aaa.bbb.ccc"
    line = redact_secrets(
        f"Authorization: Bearer {bearer} X-Mill-Directory: {directory} factory-door={bearer}"
    )
    assert bearer not in line
    assert directory not in line


def test_redact_covers_cookie_json_and_private_key():
    canary = "gln-canary-9f3a"
    line = redact_secrets(
        f'Cookie: factory-door={canary} {{"password":"{canary}","client_secret":"{canary}"}} '
        "-----BEGIN " + "PRIVATE KEY-----\n" + canary + "\n-----END " + "PRIVATE KEY-----"
    )
    assert canary not in line
    assert "password" in line
    assert "[redacted]" in line


def test_redact_covers_url_userinfo_and_frames():
    secret = "synth-hook-9f3a"
    line = redact_format(
        "webhook %s err=%s",
        f"https://hook:{secret}@hooks.example/push?token={secret}",
        f"Bearer {secret}",
    )
    assert secret not in line
    frame = redact_obj({"hint": "MAIL", "detail": f"invite={secret}", "n": 1})
    assert secret not in frame["detail"]
    assert frame["n"] == 1


def test_hint_file_redacts_secrets(_isolate_mill_home: Path):
    from agent_coord.server.hint_buf import HintBuf

    secret = "synth-bearer-9f3a"
    buf = HintBuf("DESK_grok-tui")
    buf.append_file(
        {
            "hint": "MAIL",
            "detail": f"Authorization: Bearer {secret}",
            "body": f"invite={secret}",
        }
    )
    text = buf.path.read_text(encoding="utf-8")
    assert secret not in text
    assert "[redacted]" in text


def test_log_files_omit_synthetic_secrets(_isolate_mill_home: Path):
    """Regression: the writers store [redacted], and the made-up values stay out of the files."""
    home = _isolate_mill_home
    invite = "synth-invite-9f3a"
    bearer = "synth-bearer-9f3a"
    code = "synth-code-9f3a"
    client_secret = "synth-client-9f3a"
    directory = "synth-directory-9f3a"
    door = "synth-door-9f3a"
    private = "synth-private-9f3a"
    password = "synth-password-9f3a"
    userinfo = "synth-userinfo-9f3a"
    api_log(
        f"GET /?invite={invite} code={code} "
        f"Authorization: Bearer {bearer} client_secret={client_secret} "
        f"password={password} passwd={password}"
    )
    perf_log("api.floor", 1.0, err=f"id_token={bearer} access_token={code}")
    dest_log(
        "mill-backchannel.log",
        f"X-Mill-Directory: {directory} factory-door={door} "
        f"X-Mill-Invite: {invite} PRIVATE-TOKEN: {private} "
        f"webhook https://hook:{userinfo}@hooks.example/push?token={private}",
    )
    access = home / "logs" / "mill-wall-access.log"
    access.parent.mkdir(parents=True, exist_ok=True)
    record_access(access, "GET", f"/?invite={invite}", 200, 1.0, 4)
    secrets = (invite, bearer, code, client_secret, directory, door, private, password, userinfo)
    texts = [
        (home / "mill-api.log").read_text(encoding="utf-8"),
        (home / "mill-perf.log").read_text(encoding="utf-8"),
        (home / "mill-backchannel.log").read_text(encoding="utf-8"),
        access.read_text(encoding="utf-8"),
    ]
    for text in texts:
        for secret in secrets:
            assert secret not in text
        assert "[redacted]" in text


def _logs_exception_without_redact(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _LOG_METHODS:
            continue
        base = node.func.value
        if not isinstance(base, ast.Name) or not (base.id == "_log" or base.id.endswith("_log")):
            continue
        for arg in node.args[1:]:
            if not any(isinstance(n, ast.Name) and n.id == "e" for n in ast.walk(arg)):
                continue
            wrapped = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "redact_format"
                for n in ast.walk(arg)
            )
            if not wrapped:
                hits.append(f"{path.name}:{node.lineno}")
    return hits


def test_socket_warnings_redact_exception_text():
    """Regression: a ws warning that includes an exception goes through redact_format."""
    root = Path(__file__).resolve().parents[2]
    hits: list[str] = []
    for rel in ("agent_coord/server/asgi.py", "agent_coord/server/push.py"):
        hits.extend(_logs_exception_without_redact(root / rel))
    assert hits == []


def test_agent_coord_logs_do_not_interpolate_secrets():
    """Hygiene: wall source does not pass a secret variable into a log call or a log file."""
    assert scan_agent_coord() == []


def test_log_hygiene_flags_planted_shape():
    """Regression of the hygiene check. The planted source names a variable. It holds no personal data."""
    planted = "def seat(token):\n    api_log(f'{token}')\n"
    allowed = 'def warn(desk):\n    _log.warning("ws auth bad token desk=%s", desk)\n'
    wrapped = "def seat(token):\n    api_log(redact_secrets(token))\n"
    half = "def seat(token):\n    api_log(redact_secrets(token) + token)\n"
    writer = (
        "def dump(token):\n"
        "    path = 'mill-api.log'\n"
        "    with path.open('a', encoding='utf-8') as handle:\n"
        "        handle.write(token)\n"
    )
    good_writer = (
        "def dest_log(filename, msg):\n"
        "    line = redact_secrets(msg).rstrip()\n"
        "    _log.info(line)\n"
    )
    samples = (planted, allowed, wrapped, half, writer, good_writer)
    for sample in samples:
        assert _PERSONAL.search(sample) is None
    planted_hits = findings_in_source(planted, "planted.py")
    assert planted_hits == ["planted.py:2 log interpolates token"]
    assert findings_in_source(allowed, "allowed.py") == []
    assert findings_in_source(wrapped, "wrapped.py") == []
    assert findings_in_source(half, "half.py") == ["half.py:2 log interpolates token"]
    writer_hits = findings_in_source(writer, "writer.py")
    assert "writer.py:1 dump does not call redact_secrets" in writer_hits
    assert any(hit.endswith("writes token") for hit in writer_hits)
    assert findings_in_source(good_writer, "good.py") == []
    blob = "\n".join(planted_hits + writer_hits)
    assert _PERSONAL.search(blob) is None
