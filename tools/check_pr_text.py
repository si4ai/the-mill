"""PR and issue text hygiene (card #723).

Usage:
  python tools/check_pr_text.py event        # the text of the triggering event
  python tools/check_pr_text.py sweep        # every PR and issue title, body, comment, review
  python tools/check_pr_text.py file PATH... # local text files (a body before posting)

GitHub keeps every revision of a PR or issue body in its edit history, so a
slip there stays public after an edit. Commit messages and the tree are
scanned by check_pack and precommit_hygiene; this scans the text people post
around them, with the same check_pack rules the commit-message scan uses:
non-documentation address, home path with a login segment, email outside
placeholder domains, and credential shapes (#760). PR and issue titles and
bodies also get the Title-case name-token rule (card 937 / F-pr-title-body-name-token), except
a bot-authored title and body (user.type Bot) skip that one rule and print a visible note; comments
and reviews stay on the generic rules only (too noisy for name-token).

The text is untrusted input. It is read from the event JSON file
(GITHUB_EVENT_PATH) or the API, never from a shell argument or a workflow
expression. Reports name the item, field and kind, never the matched text.
Exit 0 clean, 1 on a hit, 1 with "pr-text ERROR" when the scan cannot run.
On a pull_request event, a missing or empty ## Changelog section prints a
hint and does not fail the check. Dependabot and docs-only PRs are exempt.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_pack as cp  # noqa: E402
import docs_only  # noqa: E402

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def _name_token_field(where: str) -> bool:
    """True for PR/issue title and body; false for comments and reviews."""
    return where.endswith(" title") or where.endswith(" body")


BOT_NAME_TOKEN_SKIP = "name-token rule skipped: bot-authored body"


def _author_is_bot(obj: dict) -> bool:
    """True when the GitHub account that opened the item is type Bot."""
    return (obj.get("user") or {}).get("type") == "Bot"


def _unpack(item: tuple) -> tuple[str, str, bool]:
    """(where, text, bot). A 2-tuple (file mode, older callers) is not a bot."""
    if len(item) >= 3:
        return item[0], item[1], bool(item[2])
    return item[0], item[1], False


def bot_name_token_skipped(texts: list[tuple]) -> bool:
    """True when a PR/issue title or body is present and its author is a bot."""
    return any(
        bot and _name_token_field(where) for where, _text, bot in map(_unpack, texts)
    )


def kinds(
    text: str,
    *,
    name_token: bool = False,
    vocab: set[str] | frozenset[str] | None = None,
) -> list[tuple[int, str]]:
    """(line, kind) for every rule hit in text."""
    out: list[tuple[int, str]] = []
    words = vocab if vocab is not None else frozenset()
    for i, ln in enumerate((text or "").splitlines(), 1):
        if cp.text_has_forbidden_address(ln):
            out.append((i, "non-documentation address"))
        if cp.text_has_personal_home_path(ln):
            out.append((i, "home path with a login name"))
        if cp.text_has_personal_email(ln):
            out.append((i, "email outside placeholder domains"))
        for kind in cp.credential_kinds(ln):
            out.append((i, f"credential shape ({kind})"))
        if name_token and cp.text_has_personal_name_token(ln, words):
            out.append((i, "personal name token"))
    return out


def scan(
    texts: list[tuple[str, str]],
    *,
    vocab: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """texts is [(where, text)]; returns report lines, never the text.

    Title and body fields also run the commit-msg name-token rule (card 937),
    unless the author is a bot account (user.type Bot); then that rule is skipped
    and a visible note is printed. Comments and reviews keep the generic rules only.
    """
    words = vocab if vocab is not None else cp.ordinary_words()
    out: list[str] = []
    for item in texts:
        where, text, bot = _unpack(item)
        use_name = _name_token_field(where) and not bot
        for line, kind in kinds(text, name_token=use_name, vocab=words):
            out.append(f"{where}:{line}: {kind}")
    return out


def event_texts(name: str, event: dict) -> list[tuple[str, str]]:
    if name == "pull_request":
        pr = event.get("pull_request") or {}
        n = pr.get("number")
        bot = _author_is_bot(pr)
        return [
            (f"PR #{n} title", pr.get("title") or "", bot),
            (f"PR #{n} body", pr.get("body") or "", bot),
        ]
    if name == "issues":
        it = event.get("issue") or {}
        n = it.get("number")
        bot = _author_is_bot(it)
        return [
            (f"issue #{n} title", it.get("title") or "", bot),
            (f"issue #{n} body", it.get("body") or "", bot),
        ]
    if name in ("issue_comment", "pull_request_review_comment", "pull_request_review"):
        c = event.get("comment") or event.get("review") or {}
        n = (event.get("issue") or event.get("pull_request") or {}).get("number")
        return [(f"#{n} {name.replace('_', ' ')} {c.get('id')}", c.get("body") or "")]
    raise ValueError(f"event {name!r} has no text this check reads")


def _get(url: str, token: str) -> tuple[list, str | None]:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https API base)
        nxt = None
        for part in (r.headers.get("Link") or "").split(","):
            if 'rel="next"' in part:
                nxt = part.split(";", 1)[0].strip().strip("<>")
        return json.loads(r.read().decode("utf-8")), nxt


def _all(url: str, token: str) -> list:
    out: list = []
    while url:
        page, url = _get(url, token)
        out.extend(page)
    return out


def sweep_texts(repo: str, token: str) -> list[tuple[str, str]]:
    base = f"{API}/repos/{repo}"
    texts: list[tuple[str, str]] = []
    for it in _all(f"{base}/issues?state=all&per_page=100", token):
        what = "PR" if "pull_request" in it else "issue"
        bot = _author_is_bot(it)
        texts += [
            (f"{what} #{it['number']} title", it.get("title") or "", bot),
            (f"{what} #{it['number']} body", it.get("body") or "", bot),
        ]
        if what == "PR":  # review bodies: no workflow runs on a review event (#823, F122)
            for rv in _all(f"{base}/pulls/{it['number']}/reviews?per_page=100", token):
                texts.append((f"PR #{it['number']} review {rv['id']}", rv.get("body") or ""))
    for c in _all(f"{base}/issues/comments?per_page=100", token):
        n = (c.get("issue_url") or "").rsplit("/", 1)[-1]
        texts.append((f"#{n} comment {c['id']}", c.get("body") or ""))
    for c in _all(f"{base}/pulls/comments?per_page=100", token):
        n = (c.get("pull_request_url") or "").rsplit("/", 1)[-1]
        texts.append((f"#{n} review comment {c['id']}", c.get("body") or ""))
    return texts


CHANGELOG_HEAD = re.compile(r"^##[ \t]+Changelog[ \t]*$", re.I)
NEXT_HEAD = re.compile(r"^##[ \t]+")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
CHANGELOG_HINT = (
    "hint: PR body needs a one-line ## Changelog section "
    "(see docs/dev/CONTRIBUTING-PR.md). This hint does not fail the check."
)


def _login(obj: dict) -> str:
    return str((obj.get("user") or {}).get("login") or "")


def is_dependabot(obj: dict) -> bool:
    """True for Dependabot-authored PRs (exempt from the Changelog hint)."""
    login = _login(obj).casefold()
    return login == "dependabot[bot]" or login.startswith("dependabot")


def changelog_section_present(body: str) -> bool:
    """True when ## Changelog exists and has at least one non-empty line."""
    if not body:
        return False
    text = HTML_COMMENT.sub("", body)
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if CHANGELOG_HEAD.match(ln):
            start = i + 1
            break
    if start is None:
        return False
    for ln in lines[start:]:
        if NEXT_HEAD.match(ln):
            break
        if ln.strip():
            return True
    return False


def changelog_hint(
    body: str,
    *,
    exempt: bool = False,
) -> str | None:
    """A visible hint, never a failing check, when the Changelog section is missing or empty."""
    if exempt:
        return None
    if changelog_section_present(body):
        return None
    return CHANGELOG_HINT


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("event", "sweep", "file") or (argv[0] == "file" and len(argv) < 2):
        print(__doc__.strip())
        return 2
    try:
        if argv[0] == "event":
            name = os.environ["GITHUB_EVENT_NAME"]
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            texts = event_texts(name, event)
        elif argv[0] == "sweep":
            texts = sweep_texts(os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_TOKEN", ""))
        else:
            texts = [(p, Path(p).read_text(encoding="utf-8", errors="replace")) for p in argv[1:]]
    except (KeyError, OSError, ValueError, urllib.error.URLError) as exc:
        print(f"pr-text ERROR: the {argv[0]} scan could not run ({type(exc).__name__}); failing closed", file=sys.stderr)
        return 1
    fails = scan(texts)
    if bot_name_token_skipped(texts):
        print(BOT_NAME_TOKEN_SKIP)
    if argv[0] == "event" and os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
        except (OSError, ValueError):
            event = {}
        pr = event.get("pull_request") or {}
        # The event carries no file list: diff base...head like ci.yml's detect_docs_only.
        exempt = is_dependabot(pr) or docs_only.skip_pytest("pull_request", event)
        hint = changelog_hint(pr.get("body") or "", exempt=exempt)
        if hint:
            print(hint)
    if fails:
        print(f"pr-text hygiene FAIL: {len(fails)} hit(s) in {len(texts)} text(s)", file=sys.stderr)
        for f in fails:
            print(f"  {f}", file=sys.stderr)
        print("Edit the text above. GitHub keeps the old revision in the edit history;"
              " ask the repo owner whether to delete it.", file=sys.stderr)
        return 1
    print(f"pr-text hygiene ok: {len(texts)} text(s), 0 hits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
