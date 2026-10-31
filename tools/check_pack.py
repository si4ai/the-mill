"""Fail-closed scanner for the-mill wheel and sdist artifacts.

Usage:
  python tools/check_pack.py dist
  python tools/check_pack.py path/to.whl path/to.tar.gz

Exits 0 when both artifacts are clean; exits 1 on any fail-closed hit.
Does not print matched home-path, email, local home-user, or address substrings.

Local extra: profile names from C:\\Users, /home, /Users, and wsl.exe ls /home.
Also the computer name, and hyphenated office-alias filenames under the local
mill home. Scan artifact text, git-tracked files at the tip, and commit
messages. Login names come from the filesystem (not a word-list); CI
has none of those, so there the names come from the MILL_PRIVATE_NAMES
secret (one per line, read at runtime, never printed) and an empty list
fails closed (#339). Off CI that variable is optional and adds names. Commit messages at or after the
history-scrub cut also fail on a Title-cased Latin token that is not on
the neutral desk-word allow-list (pre-scrub history is not re-scanned).
CI clones full history (actions/checkout fetch-depth 0). A shallow clone fails
closed. A full clone that never had the cut (a fresh root, such as a public
import) scans every commit from its root. Commits read by hand and kept are
listed in NAME_TOKEN_REVIEWED.

A complete IP outside the documentation ranges fails in the wheel, the sdist,
git-tracked files (including comments), and git commit messages. That scan
runs in CI. Loopback, unspecified, and the mill-join prefixes
192.168.1. / 192.168.1.% / 192.168.1.* may stay.

A home path with a concrete login segment (C:\\Users\\<name>, /home/<name>,
/Users/<name>) and an email address outside the placeholder domains fail in
git-tracked files and git commit messages. Placeholder segments such as
<user>, example, *, and ... may stay; so may addresses under example.com,
example.org, example.net, *.example, *.test, *.invalid, *.localhost, and
GitLab and GitHub noreply domains.

A tracked symlink (git mode 120000) under a packaged path fails the tip scan, and every wheel or sdist file member must map to a tracked regular file at HEAD (generated dist-info / egg-info / PKG-INFO may stay) (#757).

A literal byte-order mark or typographic punctuation (Windows editors and
pasted dashes, arrows, quotes) fails in the same file scan. The ASCII escape
for U+FEFF may stay; that is how mill send strips a PowerShell BOM.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

BINARY_SUFFIXES = (".exe", ".dll", ".so", ".dylib", ".bin")
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
# The project local-part passes only on a noreply domain, never on a mail host.
ALLOWED_EMAIL_LOCAL = frozenset({"pyginapithon"})
_NOREPLY_DOMAINS = frozenset({"users.noreply.github.com", "users.noreply.gitlab.com", "noreply.gitlab.com"})

# Windows profile folders that are not a human login. Not a name word-list.
_SKIP_USER_DIRS = frozenset(
    {
        "public",
        "default",
        "default user",
        "all users",
        "defaultaccount",
        "wdagutilityaccount",
        "guest",
        "administrator",
        "root",
        "shared",
        "box",
    }
)


# Absolute home-path markers (word-ish prefixes). wall.local is not a home path.
HOME_MARKERS = (
    "C:\\Users\\",
    "C:/Users/",
    "/Users/",
    "/home/",
)

# RFC 5737 and RFC 3849. Loopback and unspecified are product binds, not hosts.
# Mill-join prefixes 192.168.1. / 192.168.1.% / 192.168.1.* are not complete addresses.
_DOC_V4 = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)
_DOC_V6 = ipaddress.ip_network("2001:db8::/32")
_IPV4_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{1,3}){3})(?!\d)")
# Two or more colon groups. A clock time has no hex letter and no '::'.
_IPV6_RE = re.compile(
    r"(?<![0-9A-Za-z])((?:[0-9A-Fa-f]{0,4}:){2,7}(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f]{1,4}))(?![0-9A-Za-z:])"
)


def _ipv4_allowed(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return True
    if not isinstance(ip, ipaddress.IPv4Address):
        return True
    if ip.is_loopback or ip.is_unspecified:
        return True
    return any(ip in net for net in _DOC_V4)


def _ipv6_allowed(token: str) -> bool:
    if "::" not in token and not any(c in "abcdefABCDEF" for c in token):
        return True
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        return True
    if not isinstance(ip, ipaddress.IPv6Address):
        return True
    if ip.is_loopback or ip.is_unspecified:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and (mapped.is_loopback or mapped.is_unspecified):
        return True
    return bool(ip in _DOC_V6)


# PowerShell Set-Content -Encoding utf8 writes U+FEFF. Agents also paste
# typographic dashes, arrows, and quotes. Code points only; no glyphs here.
# The ASCII escape for U+FEFF is not in this set.
_TEXT_MARKS = frozenset(
    {
        0x00A0,
        0x00B1,
        0x00B7,
        0x0394,
        0x200B,
        0x200C,
        0x200D,
        0x2013,
        0x2014,
        0x2018,
        0x2019,
        0x201C,
        0x201D,
        0x2026,
        0x2190,
        0x2191,
        0x2192,
        0x2193,
        0x2264,
        0x2713,
        0xFEFF,
    }
)
_BOM_PREFIXES = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
# Mark scan is text only. Images, fonts, and other binaries are not decoded.
_TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".css",
        ".csv",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".markdown",
        ".md",
        ".mjs",
        ".ps1",
        ".py",
        ".pyi",
        ".rhai",
        ".rst",
        ".service",
        ".sh",
        ".sql",
        ".svg",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_TEXT_NAMES = frozenset({"copying", "dockerfile", "license", "makefile", "readme"})


def _is_text_file(rel: str) -> bool:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if name in _TEXT_NAMES:
        return True
    return Path(name).suffix in _TEXT_SUFFIXES


def text_mark(text: str) -> int | None:
    """Code point of a Windows editor mark, or None. Does not match \\\\u escapes."""
    if not text:
        return None
    for ch in text:
        point = ord(ch)
        if point in _TEXT_MARKS:
            return point
    return None


def text_has_forbidden_address(text: str) -> bool:
    """True when text holds a complete IP outside the documentation ranges."""
    if not text:
        return False
    for match in _IPV4_RE.finditer(text):
        if not _ipv4_allowed(match.group(1)):
            return True
    for match in _IPV6_RE.finditer(text):
        if not _ipv6_allowed(match.group(1)):
            return True
    return False

# Placeholder login segments in a home path. Stand-ins for "any user", not names.
_HOME_PLACEHOLDERS = frozenset(
    {
        "",
        "*",
        "...",
        "\u2026",
        "example",
        "user",
        "username",
        "you",
        "name",
    }
)
# A home-path prefix, then the login segment (stops at a separator, quote,
# placeholder bracket, or whitespace). Escaped backslashes count as one.
_HOME_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:(?:\\\\|\\|/)+[Uu][Ss][Ee][Rr][Ss](?:\\\\|\\|/)+"
    r"|(?<![\w.~-])/(?:home|Users)/)"
    r"([^\\/\s\"'`<>()\[\]{}:;,|]*)"
)
# Reserved and placeholder email domains (RFC 2606 / RFC 6761), GitLab and GitHub noreply.
_PLACEHOLDER_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "users.noreply.gitlab.com",
        "noreply.gitlab.com",
        "users.noreply.github.com",
    }
)
_PLACEHOLDER_EMAIL_TLDS = frozenset({"example", "test", "invalid", "localhost"})
# name@2x.png and similar asset names are not addresses.
_ASSET_TLDS = frozenset(
    {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "js", "mjs", "css", "py", "md", "txt", "json", "whl", "gz"}
)


def home_segment_is_placeholder(segment: str) -> bool:
    seg = segment.strip().casefold()
    if seg in _HOME_PLACEHOLDERS:
        return True
    return seg[:1] in ("$", "%", "<", "{", "*", ".")


def text_has_personal_home_path(text: str) -> bool:
    """True when text holds a home path whose login segment is not a placeholder."""
    if not text:
        return False
    for match in _HOME_PATH_RE.finditer(text):
        if not home_segment_is_placeholder(match.group(1)):
            return True
    return False


def email_is_placeholder(addr: str) -> bool:
    local, _, domain = addr.rpartition("@")
    domain = domain.casefold().rstrip(".")
    # git@host is an SSH remote, not a person.
    if local == "git":
        return True
    if domain in _PLACEHOLDER_EMAIL_DOMAINS:
        return True
    if any(domain.endswith("." + d) for d in _PLACEHOLDER_EMAIL_DOMAINS):
        return True
    tld = domain.rsplit(".", 1)[-1]
    return tld in _PLACEHOLDER_EMAIL_TLDS or tld in _ASSET_TLDS


def text_has_personal_email(text: str) -> bool:
    """True when text holds an email address outside the placeholder domains."""
    if not text:
        return False
    return any(not email_is_placeholder(em) for em in EMAIL_RE.findall(text))


# Neutral Title-case tokens that may appear in commit messages. Casefold
# compare only; never a list of personal names.
DESK_WORD_ALLOWLIST = frozenset(
    {
        "add", "address", "admin", "after", "against", "agent",
        "agents", "all", "also", "and", "another", "any",
        "apache", "api", "apply", "archive", "assert", "async",
        "auth", "aws", "before", "below", "between", "body",
        "book", "both", "branch", "bridge", "brief", "briefed",
        "briefings", "briefs", "build", "builder", "bump", "but",
        "by", "cache", "call", "card", "cards", "change",
        "changes", "check", "cherry", "claim", "claims", "class",
        "clean", "client", "clip", "close", "code", "cold",
        "column", "columns", "commit", "commits", "compare", "conflict",
        "conflicts", "connect", "connection", "correct", "count", "counts",
        "create", "cut", "data", "db", "default", "delete",
        "design", "desk", "desks", "docs", "doctrine", "document",
        "documentation", "dogfood", "drop", "each", "edge", "else",
        "email", "empty", "end", "entry", "error", "errors",
        "every", "evidence", "example", "expect", "fail", "false",
        "fastapi", "fetch", "few", "file", "files", "find",
        "first", "fix", "fixtures", "flag", "floor", "focus", "follow",
        "for", "from", "front", "full", "function", "functions",
        "garden", "gardener", "get", "git", "gitlab", "given",
        "glance", "go", "graph", "graphs", "group", "high",
        "hold", "holds", "home", "host", "hosts", "how",
        "however", "http", "https", "hygiene", "install", "into",
        "issue", "issues", "item", "items", "its", "join",
        "keep", "key", "label", "labels", "lan", "large",
        "last", "later", "least", "left", "letter", "letters",
        "like", "linux", "list", "load", "local", "lock",
        "log", "loop", "loops", "mail", "main", "make",
        "mark", "measure", "merge", "message", "messages", "mill",
        "miss", "move", "must", "mysql", "name", "names",
        "need", "new", "next", "node", "none", "not",
        "note", "notes", "now", "null", "object", "objects",
        "off", "office", "one", "only", "open", "opened",
        "option", "options", "ord", "order", "other", "out",
        "over", "own", "pack", "page", "pane", "panel",
        "parent", "part", "pass", "path", "paths", "peek",
        "pending", "per", "performance", "personal", "placeholder", "plan",
        "plans", "poll", "port", "power", "print", "private",
        "project", "projects", "public", "pull", "push", "python",
        "query", "read", "readme", "ready", "record", "records",
        "refuse", "regression", "release", "reply", "report", "request", "requests",
        "require", "reset", "result", "results", "return", "review",
        "rewrite", "right", "role", "room", "rooms", "root",
        "row", "rows", "run", "same", "say", "scan",
        "score", "script", "see", "select", "send", "session",
        "set", "several", "ship", "shipper", "show", "since",
        "skip", "small", "some", "speech", "sql", "start",
        "status", "still", "stop", "string", "stub", "such",
        "summary", "sync", "table", "tables", "tag", "tags",
        "take", "task", "test", "tests", "text", "than",
        "that", "the", "their", "them", "then", "there",
        "these", "they", "this", "those", "thread", "through",
        "tip", "title", "todo", "todos", "token", "tokens",
        "tool", "tools", "top", "trail", "tree", "true",
        "try", "type", "under", "unit", "until", "update",
        "updates", "use", "used", "user", "users", "using",
        "validator", "value", "values", "verb", "verbs", "version",
        "via", "view", "wait", "wall", "want", "warm",
        "when", "where", "which", "while", "who", "why",
        "will", "windows", "with", "without", "work", "write",
        "yes", "yet", "you", "your",
    }
)

# History-scrub tip on main (2026-10-12). Name-token scan covers commits
# reachable after this cut only; older subjects stay under path/email/address rules.
# A full clone without the cut (fresh root) scans from its root commit instead.
NAME_TOKEN_SCAN_SINCE = "f3aeff8"

_NAME_TOKEN_RE = re.compile(r"\b[A-Z][a-z]{2,20}\b")

# Commits after the cut whose messages were read by hand on 2026-10-18: every
# flagged token is an ordinary word at a line start (no person's name).
# They are pushed history on main, so they stay rather than being rewritten.
# Needed while that history is scanned; a fresh root simply never has them.
# A new commit is never added here; reword it before it is pushed.
NAME_TOKEN_REVIEWED = frozenset(
    {
        "091f267f4cb858a7765b672aaf93116d6e1a5967",
        "24b23a16537bd03468e9f51953d9ae17b50121ee",
        "318fa214881c2db32dd726764fc22982ed74f700",
        "31fd424040431c13b2918b1d75ae5c19a2ecaf36",
        "3362195615438a35445dfc70e900b2364b8cc682",
        "550f1bf7720910e5739786ba71571f4c6321806d",
        "5cc39228fc1a7329cb9200efeb6368e77e75e986",
        "694f4f7eaa4585db73f5a83b536fe30fa7e61b7e",
        "8e8bf65b67ff253eb2e754b4083d886458d5f218",
        "8fc78db8ecf37defeb8fb0b20bb6fc150f40748b",
        "953bd9508feeec5adc3f95ed064dce320c23b776",
        "99a0a0a92c5522d87bc8f5dd0f7f0539100b39f7",
        "ac3a882721def95734acf20c57f4be3859621f72",
        "ae1fdcb1e72d0eaefae2c2de535a3ffbd2cdf6a2",
        "c092f559676542cbcf13f1e35b4030191d6fce7d",
        "d86c2c961c90d1814bc8bfb30a0d7be352f44ec6",
        "dc4545d651943916506038b0a7c4f222179cd440",
        "e73377e5ea82cade6676b0db0ecc5663e724979d",
        "eb9264e9364bf934c4cce48d6ae4532f8d373390",
        "eefa145ababcb04c50fefe1a1678173962ebc3e0",
        "f4e7da61194f36cc8ad0cd096c3d113b9d7a55af",
        "fa9c7e365974260fca6a0ad0f9eb3c23a0252f74",
    }
)


# The first word of a line, after an optional bullet, list number or card
# number ("- ", "1. ", "2) ", "#338 "). Sentence case puts a capital there.
_LINE_START_RE = re.compile(r"^[ \t]*(?:(?:[-*+>]|\d+[.)]|#\d+:?)[ \t]+)*([A-Z][a-z]{2,20})\b", re.MULTILINE)
# The first word of a sentence inside a line: after ".", "!" or "?" (and an
# optional closing quote or bracket) and a space. Sentence case puts a capital
# there too, mid-line (#724: "... under 2 KB. Live 0.7.14, ...").
_SENTENCE_START_RE = re.compile(r"(?<=[.!?])[\"')\]]*[ \t]+([A-Z][a-z]{2,20})\b")
_WORDS_FILE = Path(__file__).resolve().parent / "hygiene_words.txt"
_LOWER_WORD_RE = re.compile(r"\b[a-z]{3,21}\b")


def ordinary_words(root: Path | None = None, *, staged: bool = False) -> set[str]:
    """Lower-case words in the HEAD tree (or the index), plus hygiene_words.txt.

    A word the tree uses in lower case is an ordinary word; a name never is.
    A git error leaves only the word file, which is stricter, never looser.
    """
    words: set[str] = set()
    where = ["--cached", "-E", "[a-z]{3,21}"] if staged else ["-E", "[a-z]{3,21}", "HEAD"]
    try:
        raw = subprocess.check_output(
            ["git", "grep", "-h", "-o", "-w", "-I", *where, "--", "."],
            cwd=root or mill_root(),
            stderr=subprocess.DEVNULL,
        )
        words.update(_LOWER_WORD_RE.findall(raw.decode("utf-8", "replace")))
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        for ln in _WORDS_FILE.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln:
                words.add(ln.casefold())
    except OSError:
        pass
    return words


def text_has_personal_name_token(text: str, vocab: set[str] | frozenset[str] = frozenset()) -> bool:
    """True when text holds a Title-cased Latin token off the desk-word allow-list.

    The first word of a line (after a bullet, list number or card number) also
    passes when its lower-case form is in vocab, the ordinary words of the tree
    (#338). So does the first word of a sentence inside a line, after ". ",
    "! " or "? " (#724). Any other mid-line token keeps the allow-list rule
    only, and a token whose lower-case form is not an ordinary word fails at
    any position.
    """
    if not text:
        return False
    starts = {
        m.start(1)
        for rx in (_LINE_START_RE, _SENTENCE_START_RE)
        for m in rx.finditer(text)
        if m.group(1).casefold() in vocab
    }
    for match in _NAME_TOKEN_RE.finditer(text):
        if match.start() in starts:
            continue
        if match.group(0).casefold() not in DESK_WORD_ALLOWLIST:
            return True
    return False


SDIST_ROOT_RE = re.compile(r"^the_mill-[^/]+(?:/(.*))?$")
SDIST_ROOT_FILES = frozenset(
    {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "PKG-INFO",
        "setup.cfg",
        "MANIFEST.in",
        "build_backend/mill_build.py",
    }
)


def _is_bak(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    if base.endswith(".bak") or base == ".bak":
        return True
    if ".bak-" in base or base.startswith(".bak-"):
        return True
    return False


def _is_junk_name(path: str) -> str | None:
    parts = path.replace("\\", "/").split("/")
    for p in parts:
        if p == "__pycache__" or p.endswith(".pyc") or p == ".pyc":
            return "bytecode/cache"
        if p == "wall_ui_save":
            return "wall_ui_save"
        if _is_bak(p):
            return "backup"
    return None


def _email_allowed(addr: str) -> bool:
    local, _, domain = addr.rpartition("@")
    return local.casefold() in ALLOWED_EMAIL_LOCAL and domain.casefold() in _NOREPLY_DOMAINS


def _has_home_marker(text: str) -> bool:
    for m in HOME_MARKERS:
        if m in text:
            return True
    return False


def _keep_home_name(name: str) -> bool:
    n = name.strip()
    if len(n) < 3:
        return False
    if n.casefold() in _SKIP_USER_DIRS:
        return False
    if n.casefold() in ALLOWED_EMAIL_LOCAL:
        return False
    return True


def _names_under(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    try:
        kids = list(root.iterdir())
    except OSError:
        return []
    for p in kids:
        try:
            if not p.is_dir():
                continue
        except OSError:
            continue
        if _keep_home_name(p.name):
            out.append(p.name.strip())
    return out


def _wsl_home_names() -> list[str]:
    """WSL /home/* when check_pack runs on Windows with wsl.exe."""
    wsl = shutil.which("wsl")
    if not wsl:
        return []
    try:
        raw = subprocess.check_output(
            [wsl, "-e", "ls", "-1", "/home"],
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    out: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        name = line.strip()
        if _keep_home_name(name):
            out.append(name)
    return out


def _alias_dir() -> Path:
    return Path.home() / ".mill" / "alias"


def local_place_names() -> tuple[str, ...]:
    """Computer name, and hyphenated mill office aliases. Read from disk.

    A plain alias such as a short sandbox name is not a place name. Empty on
    GitLab CI.
    """
    if os.environ.get("GITLAB_CI") or os.environ.get("CI") == "true":
        return ()
    found: list[str] = []
    host = (os.environ.get("COMPUTERNAME") or socket.gethostname() or "").split(".")[0].strip()
    if _keep_home_name(host):
        found.append(host)
    root = _alias_dir()
    if root.is_dir():
        try:
            kids = list(root.iterdir())
        except OSError:
            kids = []
        for path in kids:
            try:
                if not path.is_file() or "-" not in path.name:
                    continue
            except OSError:
                continue
            if _keep_home_name(path.name):
                found.append(path.name.strip())
    return tuple(found)


def local_home_user_names() -> tuple[str, ...]:
    """Login folder names: C:\\Users, /home, /Users, and WSL /home via wsl.exe.

    Also place names from local_place_names. Empty on GitLab CI.
    """
    if os.environ.get("GITLAB_CI") or os.environ.get("CI") == "true":
        return ()
    out: list[str] = []
    out.extend(_names_under(Path(r"C:\Users")))
    out.extend(_names_under(Path("/home")))
    out.extend(_names_under(Path("/Users")))
    out.extend(_wsl_home_names())
    out.extend(local_place_names())
    return tuple(sorted(set(out), key=str.casefold))


PRIVATE_NAMES_ENV = "MILL_PRIVATE_NAMES"


def on_ci() -> bool:
    return bool(os.environ.get("GITLAB_CI")) or os.environ.get("CI") == "true"


def private_names() -> tuple[str, ...]:
    """Names from MILL_PRIVATE_NAMES, one per line (#339).

    In CI this is a repository secret, read at runtime: the names never sit in
    the repo, and reports name the kind and the path or commit, never the name.
    Off CI it is optional and adds to the names read from disk.
    """
    out = [ln.strip() for ln in os.environ.get(PRIVATE_NAMES_ENV, "").splitlines()]
    return tuple(sorted({n for n in out if n and not n.startswith("#") and _keep_home_name(n)}, key=str.casefold))


def private_names_required() -> bool:
    """On CI the list must be there; a fork PR (no secrets) sets the env to 0."""
    return on_ci() and os.environ.get(PRIVATE_NAMES_ENV + "_REQUIRED", "1") != "0"


def _home_user_regexes(names: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    pats: list[re.Pattern[str]] = []
    for n in names:
        pats.append(
            re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])",
                re.IGNORECASE,
            )
        )
    return tuple(pats)


def _has_local_home_user(text: str, pats: tuple[re.Pattern[str], ...]) -> bool:
    if not pats or not text:
        return False
    for p in pats:
        if p.search(text):
            return True
    return False


def mill_root() -> Path:
    return Path(__file__).resolve().parents[1]



# Modes git uses for tracked blobs. 120000 = symlink (card 757).
_GIT_SYMLINK_MODE = "120000"
_GIT_REGULAR_MODES = frozenset({"100644", "100755"})
# Wheel data-files land under the_mill-*.data/data/share/the-mill/<repo path>.
_WHEEL_DATA_RE = re.compile(r"^the_mill-[^/]+\.data/data/share/the-mill/(.*)$")
_WHEEL_DISTINFO_RE = re.compile(r"^the_mill-[^/]+\.dist-info(/|$)")
_SDIST_EGGINFO_RE = re.compile(r"^the_mill\.egg-info(/|$)")


def git_index_modes(root: Path | None = None) -> dict[str, str]:
    """path -> git mode string at HEAD (ls-tree). Empty dict when git is unavailable."""
    root = mill_root() if root is None else root
    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return {}
    modes: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        # <mode> <type> <sha>\t<path>
        try:
            meta, rel = line.split("\t", 1)
        except ValueError:
            continue
        mode = meta.split(" ", 1)[0]
        if rel:
            modes[rel.replace("\\", "/")] = mode
    return modes


def _packaged_path(rel: str) -> bool:
    """Paths that can ship in the wheel or sdist."""
    n = rel.replace("\\", "/")
    if n.startswith("agent_coord/") or n == "agent_coord":
        return True
    if n.startswith("docs/") or n == "docs":
        return True
    if n.startswith("tests/") or n == "tests":
        return True
    if n.startswith("build_backend/") or n == "build_backend":
        return True
    if n in SDIST_ROOT_FILES or n == "README.md" or n == "LICENSE":
        return True
    return False


def scan_git_symlinks(modes: dict[str, str] | None = None) -> list[str]:
    """Refuse mode-120000 entries under packaged paths (card 757 / F205)."""
    if modes is None:
        modes = git_index_modes()
    fails: list[str] = []
    for rel, mode in sorted(modes.items()):
        if mode == _GIT_SYMLINK_MODE and _packaged_path(rel):
            fails.append(f"symlink (mode 120000) under packaged path: {rel}")
    return fails


def pack_member_repo_path(member: str, kind: str) -> str | None:
    """Repo-relative path for a pack file member, or None when it is generated metadata."""
    n = member.replace("\\", "/").rstrip("/")
    if kind == "wheel":
        if _WHEEL_DISTINFO_RE.match(n):
            return None
        if n.startswith("agent_coord/") or n == "agent_coord":
            return n
        m = _WHEEL_DATA_RE.match(n)
        if m:
            return m.group(1) or None
        return None  # unknown wheel layout: allowlist scan already fails it
    m = SDIST_ROOT_RE.match(n)
    if not m:
        return None
    rest = m.group(1)
    if rest is None or rest == "":
        return None  # the top-level the_mill-VER/ directory entry
    if _SDIST_EGGINFO_RE.match(rest) or rest == "the_mill.egg-info":
        return None
    if rest == "PKG-INFO":
        return None  # generated at the sdist root
    return rest


def scan_pack_provenance(
    path: Path,
    kind: str,
    modes: dict[str, str] | None = None,
) -> list[str]:
    """Every file member must map to a tracked regular file at HEAD (card 757)."""
    if modes is None:
        modes = git_index_modes()
    fails: list[str] = []
    iterator = _iter_wheel if kind == "wheel" else _iter_sdist
    for name, _data, is_dir in iterator(path):
        if is_dir:
            continue
        rel = pack_member_repo_path(name, kind)
        if rel is None:
            continue
        mode = modes.get(rel)
        if mode is None:
            fails.append(f"untracked pack member: {rel}")
        elif mode == _GIT_SYMLINK_MODE:
            fails.append(f"pack member is a git symlink: {rel}")
        elif mode not in _GIT_REGULAR_MODES:
            fails.append(f"pack member is not a tracked regular file (mode {mode}): {rel}")
    return fails


def scan_git_tracked(pats: tuple[re.Pattern[str], ...]) -> list[str]:
    """Git tip: login names when pats is set, and non-documentation addresses always."""
    root = mill_root()
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    fails: list[str] = []
    for rel in raw.decode("utf-8", "replace").split("\0"):
        if not rel:
            continue
        if text_has_forbidden_address(rel):
            fails.append("non-documentation address in a git path")
            continue
        path = root / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        text = blob.decode("utf-8", "replace")
        if _has_local_home_user(text, pats):
            fails.append(f"local home-user name in git tip: {rel}")
        if text_has_forbidden_address(text):
            fails.append(f"non-documentation address in git tip: {rel}")
        if text_has_personal_home_path(text):
            fails.append(f"home path with a login name in git tip: {rel}")
        if text_has_personal_email(text):
            fails.append(f"email outside placeholder domains in git tip: {rel}")
        if _is_text_file(rel):
            if blob.startswith(_BOM_PREFIXES):
                fails.append(f"byte-order mark in git tip: {rel}")
            mark = text_mark(text)
            if mark is not None:
                fails.append(f"windows text mark U+{mark:04X} in git tip: {rel}")
    return fails


def name_token_cut_present(root: Path) -> bool:
    """True when the clone holds the scrub-cut commit (a shallow clone may not)."""
    try:
        subprocess.check_output(
            ["git", "cat-file", "-e", f"{NAME_TOKEN_SCAN_SINCE}^{{commit}}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def clone_is_shallow(root: Path) -> bool:
    """True for a shallow clone. An unreadable answer counts as shallow (fail closed)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return True
    return out.decode().strip() != "false"


def _name_token_scan_revs(root: Path, cut_present: bool = True) -> frozenset[str]:
    """Commits on HEAD that the name-token rule covers.

    With the cut: commits that descend from NAME_TOKEN_SCAN_SINCE (exclusive).
    Use --ancestry-path so alternate pre-rewrite tips (stale MR refs still
    reachable via git log --all) are not treated as "after" the scrub cut.
    Without the cut (a full clone of a fresh root): every commit on HEAD,
    root included. Name-token scope is the checked-out line only; other
    message checks still walk --all.
    """
    if cut_present:
        args = ["git", "rev-list", "--ancestry-path", f"{NAME_TOKEN_SCAN_SINCE}..HEAD"]
    else:
        args = ["git", "rev-list", "HEAD"]
    try:
        raw = subprocess.check_output(
            args,
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return frozenset()
    return frozenset(line.strip() for line in raw.decode().splitlines() if line.strip())


# Dependabot's own commits on GitHub. Exact identity only, never all of
# github.com. The address is assembled so this file passes its own tree scan.
_BOT_ADDRESS = "support" + "@" + "github.com"
DEPENDABOT_AUTHOR = "49699333+dependabot[bot]" + "@" + "users.noreply.github.com"
DEPENDABOT_TRAILER = "Signed-off-by: dependabot[bot] <" + _BOT_ADDRESS + ">"


def is_dependabot_commit(author: str, body: str) -> bool:
    """True for a commit authored by Dependabot that carries its sign-off trailer."""
    return author.strip() == DEPENDABOT_AUTHOR and DEPENDABOT_TRAILER in body.splitlines()


# The Copilot coding agent on GitHub (S-12, #343). Exact identity only: its
# commits are authored by this address, it adds this co-author line, and a
# squash merge keeps the line. Assembled like the Dependabot address.
COPILOT_AGENT_AUTHOR = "198982749+" + "Cop" + "ilot" + "@" + "users.noreply.github.com"
COPILOT_COAUTHOR_TRAILER = "Co-authored-by: copilot-swe-agent[bot] <" + COPILOT_AGENT_AUTHOR + ">"
# The subject of the empty commit the agent writes before any change.
COPILOT_PLAN_SUBJECT = "Initial plan"
_BOT_TRAILERS = frozenset({DEPENDABOT_TRAILER, COPILOT_COAUTHOR_TRAILER})


def strip_bot_trailers(body: str) -> str:
    """Drop the exact Dependabot sign-off and Copilot co-author lines; any other address still counts."""
    return "\n".join(ln for ln in body.splitlines() if ln.strip() not in _BOT_TRAILERS)


def name_scan_text(author: str, body: str) -> str:
    """The message text the name-token rule reads.

    Only for a commit by the exact Copilot agent address, a first line that is
    exactly its plan subject is left out. The rest of the message is read.
    """
    if author.strip() != COPILOT_AGENT_AUTHOR:
        return body
    first, sep, rest = body.partition("\n")
    if first.rstrip() == COPILOT_PLAN_SUBJECT:
        return rest
    return body


# GitHub's own committer on web merges and bot commits. Assembled like the
# Dependabot address so this file passes its own tree scan.
GITHUB_WEB_FLOW = "noreply" + "@" + "github.com"


def identity_email_ok(addr: str) -> bool:
    """Author and committer emails: a GitHub noreply address or GitHub's own committer."""
    addr = addr.strip()
    _, at, domain = addr.rpartition("@")
    if not at:
        return False
    return domain.casefold() == "users.noreply.github.com" or addr.casefold() == GITHUB_WEB_FLOW


def scan_git_identities() -> list[str]:
    """Every commit's author and committer email is noreply (S-10).

    A web merge stamps the merging account's commit email. With email privacy
    off that is a personal address, so a push to main fails loudly here. The
    report is the hash and the role, never the address.
    """
    root = mill_root()
    try:
        raw = subprocess.check_output(
            ["git", "log", "--all", "--format=%H%x1f%ae%x1f%ce"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    fails: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        rev, _, rest = line.partition("\x1f")
        author, _, committer = rest.partition("\x1f")
        if not rev:
            continue
        if not identity_email_ok(author):
            fails.append(f"author email is not noreply in git commit {rev[:12]}")
        if not identity_email_ok(committer):
            fails.append(f"committer email is not noreply in git commit {rev[:12]}")
    return fails


def scan_git_messages(pats: tuple[re.Pattern[str], ...] = ()) -> list[str]:
    """Commit subjects and bodies. The report is the hash, not the message.

    Home-user / address / home-path / email checks cover all commits. The
    Title-case name-token rule runs only for HEAD commits after
    NAME_TOKEN_SCAN_SINCE (--ancestry-path), or for every HEAD commit in a
    full clone that has no cut. A shallow clone without the cut fails closed.
    The exact Dependabot sign-off trailer is not an email hit, and a commit by
    the Dependabot identity with that trailer skips the name-token rule (its
    text is generated, not written by a desk).
    """
    root = mill_root()
    try:
        raw = subprocess.check_output(
            ["git", "log", "--all", "--format=%H%x1f%ae%x1e%B%x1e"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    cut_present = name_token_cut_present(root)
    name_revs = _name_token_scan_revs(root, cut_present)
    vocab = ordinary_words(root)
    fails: list[str] = []
    # A shallow clone (the CI default depth) lacks the cut, and the rule
    # used to pass silently there. Fail closed so CI checks what a full clone does.
    # A full clone without the cut is a fresh root: scanned from the root above.
    if not cut_present and clone_is_shallow(root):
        fails.append(
            f"name-token scan cut {NAME_TOKEN_SCAN_SINCE} is not in this clone"
            " (shallow?); fetch full history (fetch-depth 0)"
        )
    parts = raw.decode("utf-8", "replace").split("\x1e")
    index = 0
    while index + 1 < len(parts):
        rev, _, author = parts[index].strip().partition("\x1f")
        body = parts[index + 1]
        index += 2
        if not rev:
            continue
        bot = is_dependabot_commit(author, body)
        body = strip_bot_trailers(body)
        if _has_local_home_user(body, pats):
            fails.append(f"local home-user name in git commit {rev[:12]}")
        if text_has_forbidden_address(body):
            fails.append(f"non-documentation address in git commit {rev[:12]}")
        if text_has_personal_home_path(body):
            fails.append(f"home path with a login name in git commit {rev[:12]}")
        if text_has_personal_email(body):
            fails.append(f"email outside placeholder domains in git commit {rev[:12]}")
        if (
            rev in name_revs
            and rev not in NAME_TOKEN_REVIEWED
            and not bot
            and text_has_personal_name_token(name_scan_text(author, body), vocab)
        ):
            fails.append(f"personal name token in git commit {rev[:12]}")
    return fails


def scan_head_message(pats: tuple[re.Pattern[str], ...] = ()) -> list[str]:
    """The HEAD commit message alone, every message rule (#810, F109).

    In the GitHub merge queue HEAD is the squash commit that lands on main
    as is, so its message is scanned before it gets there: the private and
    local names, addresses, home paths, emails and the name-token rule. The
    name-token rule runs here whatever the cut, so a shallow clone checks it
    too. The report is the hash, not the message.
    """
    root = mill_root()
    try:
        raw = subprocess.check_output(
            ["git", "log", "-1", "--format=%H%x1f%ae%x1e%B", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return ["cannot read the HEAD commit message (failing closed)"]
    head, _, body = raw.decode("utf-8", "replace").partition("\x1e")
    rev, _, author = head.strip().partition("\x1f")
    where = f"the queued message {rev[:12]}"
    bot = is_dependabot_commit(author, body)
    body = strip_bot_trailers(body)
    fails: list[str] = []
    if _has_local_home_user(body, pats):
        fails.append(f"local home-user name in {where}")
    if text_has_forbidden_address(body):
        fails.append(f"non-documentation address in {where}")
    if text_has_personal_home_path(body):
        fails.append(f"home path with a login name in {where}")
    if text_has_personal_email(body):
        fails.append(f"email outside placeholder domains in {where}")
    if not bot and text_has_personal_name_token(name_scan_text(author, body), ordinary_words(root)):
        fails.append(f"personal name token in {where}")
    return fails


def head_message_main() -> int:
    """check_pack.py --head-message: the merge-queue step (no dist needed)."""
    names = private_names()
    if not names and private_names_required():
        print(f"FAIL: CI needs the {PRIVATE_NAMES_ENV} secret for the queued-message scan (fail-closed)")
        return 1
    pats = _home_user_regexes(tuple(sorted(set(local_home_user_names()) | set(names), key=str.casefold)))
    fails = scan_head_message(pats)
    if fails:
        print(f"FAIL: {len(fails)} issue(s) in the HEAD commit message")
        for f in fails:
            print(f"  - {f}")
        print("Fix the PR title or body (the squash message) and queue it again.")
        return 1
    print("OK: the HEAD commit message passed the message rules.")
    return 0


def _under_agent_coord(member: str, kind: str) -> bool:
    n = member.replace("\\", "/")
    if kind == "wheel":
        return n.startswith("agent_coord/")
    m = SDIST_ROOT_RE.match(n)
    if not m:
        return False
    rest = m.group(1) or ""
    return rest.startswith("agent_coord/")


def _under_tests(member: str, kind: str) -> bool:
    if kind != "sdist":
        return False
    n = member.replace("\\", "/")
    m = SDIST_ROOT_RE.match(n)
    if not m:
        return False
    rest = m.group(1) or ""
    return rest.startswith("tests/")


def _allowlisted(member: str, kind: str) -> bool:
    n = member.replace("\\", "/").rstrip("/")
    if kind == "wheel":
        if n.startswith("agent_coord/") or n == "agent_coord":
            return True
        if re.match(r"^the_mill-[^/]+\.dist-info(/|$)", n):
            return True
        if re.match(r"^the_mill-[^/]+\.data/data/share/the-mill(/|$)", n):
            return True
        return False

    m = SDIST_ROOT_RE.match(n)
    if not m:
        return False
    rest = m.group(1)
    if rest is None or rest == "":
        return True
    if rest in SDIST_ROOT_FILES or rest == "build_backend":
        return True
    if rest.startswith("agent_coord/") or rest == "agent_coord":
        return True
    if rest.startswith("tests/") or rest == "tests":
        return True
    if rest.startswith("docs/") or rest == "docs":
        return True
    if rest.startswith("the_mill.egg-info/") or rest == "the_mill.egg-info":
        return True
    return False


def _newest(dist_dir: Path, pattern: str) -> Path | None:
    hits = sorted(dist_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def _iter_wheel(path: Path):
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                yield name, b"", True
                continue
            yield name, zf.read(info), False


def _iter_sdist(path: Path):
    with tarfile.open(path, "r:gz") as tf:
        for member in tf.getmembers():
            name = member.name.replace("\\", "/")
            if member.isdir():
                yield name if name.endswith("/") else name + "/", b"", True
                continue
            if not member.isfile():
                continue
            f = tf.extractfile(member)
            data = f.read() if f is not None else b""
            yield name, data, False


def scan_artifact(
    path: Path,
    kind: str,
    *,
    home_user_pats: tuple[re.Pattern[str], ...] = (),
) -> tuple[list[str], list[str]]:
    """Return (failures, leftover_notes)."""
    fails: list[str] = []
    notes: list[str] = []
    iterator = _iter_wheel if kind == "wheel" else _iter_sdist

    for name, data, is_dir in iterator(path):
        norm = name.replace("\\", "/").rstrip("/")
        display = norm

        if not _allowlisted(norm, kind):
            fails.append(f"path outside allowlist: {display}")

        junk = _is_junk_name(norm)
        if junk:
            fails.append(f"{junk} path: {display}")

        if is_dir:
            if text_has_forbidden_address(norm):
                fails.append(f"non-documentation address in a {kind} path")
            continue

        lower = norm.casefold()
        if _under_agent_coord(norm, kind) and lower.endswith(BINARY_SUFFIXES):
            fails.append(f"surprise binary under agent_coord/: {display}")

        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

        if _is_text_file(norm):
            if data.startswith(_BOM_PREFIXES):
                fails.append(f"byte-order mark in: {display}")
            mark = text_mark(text)
            if mark is not None:
                fails.append(f"windows text mark U+{mark:04X} in: {display}")

        if _has_home_marker(text):
            fails.append(f"absolute home-path string in: {display}")

        if _has_local_home_user(text, home_user_pats):
            fails.append(f"local home-user name in: {display}")

        for em in EMAIL_RE.findall(text):
            if not _email_allowed(em):
                fails.append(f"email-looking string in: {display}")
                break


        if re.search(r"Sudoku", text, re.IGNORECASE):
            if _under_agent_coord(norm, kind):
                fails.append(f"Sudoku leftover under agent_coord/: {display}")
            elif _under_tests(norm, kind):
                notes.append(f"leftover (tests, not fail): Sudoku in {display}")

        if text_has_forbidden_address(norm):
            fails.append(f"non-documentation address in a {kind} path")
        elif text_has_forbidden_address(text):
            fails.append(f"non-documentation address in: {display}")

    return fails, notes


def resolve_artifacts(args: list[str]) -> tuple[Path, Path]:
    if len(args) == 1 and Path(args[0]).is_dir():
        dist = Path(args[0])
        whl = _newest(dist, "*.whl")
        sdist = _newest(dist, "*.tar.gz")
        if whl is None or sdist is None:
            raise SystemExit(f"need both a .whl and a .tar.gz in {dist}")
        return whl, sdist
    if len(args) == 2:
        a, b = Path(args[0]), Path(args[1])
        paths = [a, b]
        whls = [p for p in paths if p.suffix == ".whl"]
        sdists = [p for p in paths if p.name.endswith(".tar.gz")]
        if len(whls) != 1 or len(sdists) != 1:
            raise SystemExit("pass one .whl and one .tar.gz (or a dist/ directory)")
        return whls[0], sdists[0]
    raise SystemExit("usage: python tools/check_pack.py dist | <wheel> <sdist>")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        print()
        print("usage: python tools/check_pack.py dist | <wheel> <sdist> | --head-message")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    if argv == ["--head-message"]:
        return head_message_main()

    whl, sdist = resolve_artifacts(argv)
    all_fails: list[str] = []
    all_notes: list[str] = []
    home_names = local_home_user_names()
    secret_names = private_names()
    home_pats = _home_user_regexes(tuple(sorted(set(home_names) | set(secret_names), key=str.casefold)))
    if home_names:
        print(f"Local name scan: {len(home_names)} name(s) from profile folders, the computer name, and hyphenated office aliases")
    else:
        print("Local home-user scan: skipped (no C:\\Users)")
    if secret_names:
        print(f"Private-name scan: {len(secret_names)} name(s) from {PRIVATE_NAMES_ENV}")
    elif private_names_required():
        all_fails.append(
            f"[ci] private-name list is empty: CI needs the {PRIVATE_NAMES_ENV} secret"
            " for the local-name scan; it fails closed without it"
        )
    elif on_ci():
        print(f"Private-name scan: skipped ({PRIVATE_NAMES_ENV}_REQUIRED=0, a fork PR has no secrets; the push to main scans)")

    for label, path, kind in (("wheel", whl, "wheel"), ("sdist", sdist, "sdist")):
        print(f"Scanning {label}: {path.name}")
        fails, notes = scan_artifact(path, kind, home_user_pats=home_pats)
        all_fails.extend(f"[{label}] {f}" for f in fails)
        all_notes.extend(f"[{label}] {n}" for n in notes)

    print("Scanning git tip (tracked files and commit messages)")
    tip_modes = git_index_modes()
    all_fails.extend(f"[git] {f}" for f in scan_git_tracked(home_pats))
    all_fails.extend(f"[git] {f}" for f in scan_git_symlinks(tip_modes))
    all_fails.extend(f"[git] {f}" for f in scan_git_messages(home_pats))
    all_fails.extend(f"[git] {f}" for f in scan_git_identities())

    print("Scanning pack provenance (members must be tracked regular files)")
    for label, path, kind in (("wheel", whl, "wheel"), ("sdist", sdist, "sdist")):
        all_fails.extend(f"[{label}] {f}" for f in scan_pack_provenance(path, kind, tip_modes))

    for n in all_notes:
        print(n)

    if all_fails:
        print()
        print(f"FAIL: {len(all_fails)} pack issue(s)")
        for f in all_fails:
            print(f"  - {f}")
        print("Pack check failed (fail-closed).")
        return 1

    print()
    print("OK: wheel, sdist, and git tip passed fail-closed pack checks.")
    if all_notes:
        print(f"(noted {len(all_notes)} tests leftover(s); not failing this slice)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
