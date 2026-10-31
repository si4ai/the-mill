"""Pack hygiene: home paths, emails, addresses, and commit-message name tokens.

Every fixture is invented placeholder data. Forbidden shapes are assembled at
run time so this file itself stays clean under the git-tip scan.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("check_pack", ROOT / "tools" / "check_pack.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _j(*parts: str) -> str:
    return "".join(parts)


BS = "\\"
LOGIN = _j("fixture", "login")


def test_home_path_with_login_fails() -> None:
    mod = _mod()
    for text in (
        _j("C:", BS, "Users", BS, LOGIN, BS, "mill"),
        _j("c:", BS, BS, "users", BS, BS, LOGIN),
        _j("C:/Users/", LOGIN, "/AppData"),
        _j("/", "home", "/", LOGIN, "/.mill"),
        _j("/", "Users", "/", LOGIN, "/Library"),
        _j('path = "/', 'home/', LOGIN, '"'),
    ):
        assert mod.text_has_personal_home_path(text), text


def test_home_path_placeholders_pass() -> None:
    mod = _mod()
    for text in (
        "C:\\Users\\<user>\\.mill",
        "C:\\Users\\example\\.mill",
        "C:/Users/<you>/AppData",
        "C:\\Users\\%USERNAME%\\.mill",
        "C:\\Users\\$env:USERNAME",
        "C:\\Users\\",
        "C:\\Users\\...",
        "/home/<user>/.mill",
        "/home/example/.mill",
        "/home/$USER/.mill",
        "/home/${USER}/.mill",
        "/home/*",
        "/Users/<user>/Library",
        "under /home/ on Linux",
        "https://docs.example.com/home/intro",
        "~/.mill/home/desk",
        "",
    ):
        assert not mod.text_has_personal_home_path(text), text


def test_email_outside_placeholder_domains_fails() -> None:
    mod = _mod()
    assert mod.text_has_personal_email(_j("someone", "@", "corp", ".", "com"))
    assert mod.text_has_personal_email(_j("To: ", "first.last", "@", "mail", ".", "co"))


def test_email_placeholders_pass() -> None:
    mod = _mod()
    for text in (
        "a@office.example",
        "desk@example.com",
        "desk@sub.example.org",
        "x@example.net",
        "build@host.test",
        "nobody@nowhere.invalid",
        "me@box.localhost",
        "bot@users.noreply.gitlab.com",
        "12345+bot@users.noreply.github.com",
        "git@gitlab.com:group/repo.git",
        "icon@2x.png",
        "GRANT mill@192.168.1.%",
        "user@<host>",
        "<user>@<host>",
        "pip install pkg@1.2",
        "",
    ):
        assert not mod.text_has_personal_email(text), text


def test_addresses_loopback_and_doc_ranges_only() -> None:
    mod = _mod()
    for octets in ((10, 0, 0, 5), (172, 16, 4, 2), (192, 168, 0, 9), (8, 8, 4, 4)):
        assert mod.text_has_forbidden_address("host " + ".".join(map(str, octets)))
    for text in ("127.0.0.1", "0.0.0.0", "203.0.113.5", "198.51.100.7", "192.0.2.1", "v1.2.3", "1.2.3"):
        assert not mod.text_has_forbidden_address(text), text


def test_box_seat_skips_css_and_home_path_still_fails() -> None:
    mod = _mod()
    assert mod._keep_home_name("box") is False
    css = "box-shadow: 0 1px rgba(0, 0, 0, 0.4);"
    kept = tuple(n for n in ("box",) if mod._keep_home_name(n))
    assert mod._has_local_home_user(css, mod._home_user_regexes(kept)) is False
    home = _j("C:", BS, "Users", BS, "box", BS, "mill")
    assert mod.text_has_personal_home_path(home)
    assert mod._has_local_home_user(home, mod._home_user_regexes(("box",)))
    suffixed = _j(LOGIN, "-pc")
    assert mod._has_local_home_user(suffixed, mod._home_user_regexes((LOGIN,)))
    real = _j("C:", BS, "Users", BS, LOGIN, BS, "mill")
    assert mod._has_local_home_user(real, mod._home_user_regexes((LOGIN,)))


def test_false_positive_words_pass() -> None:
    mod = _mod()
    text = "challenge the homepage; /homework and Users guide; workstation HOME=~"
    assert not mod.text_has_personal_home_path(text)
    assert not mod.text_has_personal_email(text)
    assert not mod.text_has_forbidden_address(text)


def test_git_scans_cover_new_rules() -> None:
    src = (ROOT / "tools" / "check_pack.py").read_text(encoding="utf-8")
    assert "home path with a login name in git tip" in src
    assert "email outside placeholder domains in git commit" in src
    mod = _mod()
    assert not mod.text_has_personal_home_path(src)
    assert not mod.text_has_personal_email(src)
    assert mod.scan_git_tracked(()) == []
    assert mod.scan_git_messages() == []


def test_commit_message_personal_name_token_fails() -> None:
    """Title-cased token off the desk-word allow-list fails (assembled at runtime)."""
    mod = _mod()
    # Invented token; joined so no contiguous personal name literal sits in this file.
    who = _j("W", "ibble")
    body = _j(who, " chose the paragraph over table rows")
    assert mod.text_has_personal_name_token(body), body
    assert who.casefold() not in mod.DESK_WORD_ALLOWLIST


def test_commit_message_allowlisted_tokens_pass() -> None:
    mod = _mod()
    for text in (
        "Docs: keep Loops and graphs under the comparison table",
        "Merge branch fix into main",
        "Bump the mill pack",
        "Builder notes the Wall Loop",
        "Add name-token scan to commit-message hygiene",
        "Speech for labels; Refuse an unknown project",
        "Without -r the newest connect wins. Regression row F43 (connect-refuse).",
        "ranks a card for it. Focus cards are the ones the desk can work on.",
        "",
    ):
        assert not mod.text_has_personal_name_token(text), text


def test_git_message_scan_clean_on_tip() -> None:
    """Scan stays clean: name-token rule is gated to post-scrub HEAD ancestry."""
    mod = _mod()
    src = (ROOT / "tools" / "check_pack.py").read_text(encoding="utf-8")
    assert "personal name token in git commit" in src
    assert mod.NAME_TOKEN_SCAN_SINCE == "f3aeff8"
    assert "--ancestry-path" in src and "NAME_TOKEN_SCAN_SINCE" in src
    assert mod.scan_git_messages() == []


def test_shallow_clone_fails_closed_on_the_name_token_cut(monkeypatch) -> None:
    """A clone without the scrub cut used to skip the name-token rule silently."""
    mod = _mod()
    monkeypatch.setattr(mod, "name_token_cut_present", lambda root: False)
    monkeypatch.setattr(mod, "clone_is_shallow", lambda root: True)
    fails = mod.scan_git_messages()
    assert any(mod.NAME_TOKEN_SCAN_SINCE in f and "shallow" in f for f in fails), fails


def test_reviewed_commits_are_full_shas_and_ci_clones_full_history() -> None:
    mod = _mod()
    assert mod.NAME_TOKEN_REVIEWED
    assert all(len(s) == 40 and int(s, 16) >= 0 for s in mod.NAME_TOKEN_REVIEWED)
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in ci.split("\n  check_pack:\n", 1)[1]


# Fresh-root clones (S-8): a public import is one root commit with no scrub cut.

_GIT_ID = (
    "-c", "user.name=fixture desk",
    "-c", "user.email=desk@example.com",
    "-c", "commit.gpgsign=false",
    "-c", "core.hooksPath=/dev/null",
)


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *_GIT_ID, *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _fresh_root(path: Path, *messages: str) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    for i, msg in enumerate(messages):
        (path / "f.txt").write_text(str(i), encoding="ascii")
        _git(path, "add", "f.txt")
        _git(path, "commit", "-q", "-m", msg)
    return path


def _scan_in(monkeypatch, repo: Path):
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    return mod, mod.scan_git_messages()


def test_fresh_root_full_clone_without_cut_passes_clean(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "the-mill 0.7.6: initial public import")
    mod, fails = _scan_in(monkeypatch, repo)
    assert not mod.name_token_cut_present(repo)
    assert not mod.clone_is_shallow(repo)
    assert fails == [], fails


def test_fresh_root_scans_the_root_commit_for_name_tokens(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    repo = _fresh_root(tmp_path / "r", _j("import tree for ", who))
    _mod_, fails = _scan_in(monkeypatch, repo)
    root = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    assert fails == [f"personal name token in git commit {root[:12]}"], fails


def test_fresh_root_scans_later_commits_too(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    repo = _fresh_root(tmp_path / "r", "initial public import", _j("fix for ", who))
    _mod_, fails = _scan_in(monkeypatch, repo)
    tip = _git(repo, "rev-parse", "HEAD")
    assert fails == [f"personal name token in git commit {tip[:12]}"], fails


def test_fresh_root_shallow_clone_still_fails_closed(tmp_path, monkeypatch) -> None:
    src = _fresh_root(tmp_path / "src", "initial public import", "second commit")
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", src.as_uri(), str(shallow))
    mod, fails = _scan_in(monkeypatch, shallow)
    assert mod.clone_is_shallow(shallow)
    assert any(mod.NAME_TOKEN_SCAN_SINCE in f and "shallow" in f for f in fails), fails


def test_unreadable_shallow_state_counts_as_shallow(tmp_path) -> None:
    mod = _mod()
    assert mod.clone_is_shallow(tmp_path / "not-a-repo")


# Dependabot on GitHub (S-8): its generated commits carry a fixed sign-off.

_BOT_AUTHOR = _j("49699333+dependabot[bot]", "@", "users.noreply.github.com")
_BOT_TRAILER = _j("Signed-off-by: dependabot[bot] <", "support", "@", "github.com", ">")


def _commit_as(repo: Path, author: str, msg: str) -> str:
    (repo / "f.txt").write_text(msg, encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "-c", "user.name=bot", "-c", f"user.email={author}", "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _bot_body() -> str:
    return _j("Bump html-validate\n\nBumps [html-validate] from 1 to 2.\n\n", _BOT_TRAILER, "\n")


def test_dependabot_commit_with_its_trailer_passes(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    _commit_as(repo, _BOT_AUTHOR, _bot_body())
    mod, fails = _scan_in(monkeypatch, repo)
    assert mod.DEPENDABOT_TRAILER == _BOT_TRAILER
    assert fails == [], fails


def test_bot_address_outside_the_trailer_still_fails(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    addr = _j("support", "@", "github.com")
    rev = _commit_as(repo, _BOT_AUTHOR, _j(_bot_body(), "\nask ", addr, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert f"email outside placeholder domains in git commit {rev[:12]}" in fails, fails


def test_other_github_address_still_fails(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    other = _j("Signed-off-by: someone <", "desk", "@", "github.com", ">")
    rev = _commit_as(repo, _BOT_AUTHOR, _j("bump a pin\n\n", other, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert f"email outside placeholder domains in git commit {rev[:12]}" in fails, fails


def test_trailer_from_a_non_bot_author_keeps_the_name_rule(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    who = _j("W", "ibble")
    rev = _commit_as(repo, "desk@example.com", _j("fix for ", who, "\n\n", _BOT_TRAILER, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert fails == [f"personal name token in git commit {rev[:12]}"], fails


# Commit identities (S-10): authors and committers stay noreply.

_NOREPLY = _j("344578673+desk", "@", "users.noreply.github.com")


def _commit_identity(repo: Path, author: str, committer: str, msg: str = "plain change") -> str:
    (repo / "f.txt").write_text(msg + author, encoding="utf-8")
    _git(repo, "add", "f.txt")
    env_args = ("-c", f"user.email={committer}", "-c", "user.name=desk")
    _git(repo, *env_args, "commit", "-q", "-m", msg, f"--author=desk <{author}>")
    return _git(repo, "rev-parse", "HEAD")


def test_identity_emails_noreply_and_web_flow_pass() -> None:
    mod = _mod()
    assert mod.identity_email_ok(_NOREPLY)
    assert mod.identity_email_ok(_j("49699333+dependabot[bot]", "@", "users.noreply.github.com"))
    assert mod.identity_email_ok(_j("noreply", "@", "github.com"))
    for bad in (
        _j("pyginapithon", "@", "mailhost.example"),
        _j("desk", "@", "github.com"),
        _j("desk", "@", "example.com"),
        "",
        "no-at-sign",
    ):
        assert not mod.identity_email_ok(bad), bad


def test_personal_committer_email_fails_by_hash_only(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    personal = _j("desk", "@", "mail-host.co")
    rev = _commit_identity(repo, _NOREPLY, personal)
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    fails = mod.scan_git_identities()
    assert f"committer email is not noreply in git commit {rev[:12]}" in fails, fails
    assert not any("mail-host" in f for f in fails)


def test_personal_author_email_fails(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    rev = _commit_identity(repo, _j("desk", "@", "mail-host.co"), _NOREPLY)
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    assert f"author email is not noreply in git commit {rev[:12]}" in mod.scan_git_identities()


def test_noreply_history_passes(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    _git(repo, "-c", f"user.email={_NOREPLY}", "commit", "-q", "--amend", "--no-edit", "--reset-author")
    _commit_identity(repo, _NOREPLY, _j("noreply", "@", "github.com"))
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    assert mod.scan_git_identities() == []


def test_project_local_part_needs_a_noreply_domain() -> None:
    mod = _mod()
    assert not mod.email_is_placeholder(_j("pyginapithon", "@", "mailhost.co"))
    assert mod.email_is_placeholder(_j("pyginapithon", "@", "users.noreply.github.com"))
    assert not mod._email_allowed(_j("pyginapithon", "@", "mailhost.co"))
    assert mod._email_allowed(_j("pyginapithon", "@", "users.noreply.github.com"))


# The Copilot coding agent on GitHub (S-12, #343): its generated first commit
# and the co-author trailer it adds, which a squash keeps. Exact identity only.

_COPILOT_AUTHOR = _j("198982749+", "Cop", "ilot", "@", "users.noreply.github.com")
_COPILOT_TRAILER = _j("Co-authored-by: copilot-swe-agent[bot] <", _COPILOT_AUTHOR, ">")
_DESK_NOREPLY = _j("344578673+desk", "@", "users.noreply.github.com")
_DESK_TRAILER = _j("Co-authored-by: desk <", _DESK_NOREPLY, ">")


def _plan_body() -> str:
    return _j("Initial plan\n\n", _DESK_TRAILER, "\n")


def test_copilot_initial_plan_commit_passes(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    _commit_as(repo, _COPILOT_AUTHOR, _plan_body())
    mod, fails = _scan_in(monkeypatch, repo)
    assert fails == [], fails
    assert mod.COPILOT_AGENT_AUTHOR == _COPILOT_AUTHOR


def test_copilot_coauthor_trailer_passes_on_a_desk_squash(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    msg = _j("#343 skip the copilot trailer (#30)\n\n", _COPILOT_TRAILER, "\n", _DESK_TRAILER, "\n")
    _commit_as(repo, _DESK_NOREPLY, msg)
    mod, fails = _scan_in(monkeypatch, repo)
    assert fails == [], fails
    assert mod.COPILOT_COAUTHOR_TRAILER == _COPILOT_TRAILER


def test_initial_plan_by_another_author_keeps_the_name_rule(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    who = _j("W", "ibble")
    rev = _commit_as(repo, _DESK_NOREPLY, _j("Initial plan\n\nfor ", who, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert fails == [f"personal name token in git commit {rev[:12]}"], fails


def test_copilot_commit_body_keeps_the_name_rule(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    who = _j("W", "ibble")
    rev = _commit_as(repo, _COPILOT_AUTHOR, _j("Initial plan\n\nasked by ", who, "\n\n", _DESK_TRAILER, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert fails == [f"personal name token in git commit {rev[:12]}"], fails


def test_copilot_later_commit_subject_keeps_the_name_rule(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    who = _j("W", "ibble")
    rev = _commit_as(repo, _COPILOT_AUTHOR, _j("fix the scan for ", who, "\n\n", _COPILOT_TRAILER, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert fails == [f"personal name token in git commit {rev[:12]}"], fails


def test_a_near_copilot_trailer_is_not_stripped(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    near = _j("Co-authored-by: Cop", "ilot <", _COPILOT_AUTHOR, ">")
    rev = _commit_as(repo, _DESK_NOREPLY, _j("#343 plain change\n\n", near, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert fails == [f"personal name token in git commit {rev[:12]}"], fails


def test_copilot_trailer_does_not_hide_an_address(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "initial public import")
    addr = _j("someone", "@", "github.com")
    rev = _commit_as(repo, _COPILOT_AUTHOR, _j("Initial plan\n\nask ", addr, "\n\n", _COPILOT_TRAILER, "\n"))
    _mod_, fails = _scan_in(monkeypatch, repo)
    assert f"email outside placeholder domains in git commit {rev[:12]}" in fails, fails


# #810 (F109): in the merge queue HEAD is the squash commit GitHub will land
# on main. check_pack --head-message scans that one message with every
# message rule, name token included, even in a shallow clone.
def _head_in(monkeypatch, repo: Path, names: tuple[str, ...] = ()):
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    return mod, mod.scan_head_message(mod._home_user_regexes(names))


def test_head_message_clean_passes(tmp_path, monkeypatch) -> None:
    repo = _fresh_root(tmp_path / "r", "older commit", "#810 repo links name the org (#150)\n\nlinks and one-liners move too.")
    _mod_, fails = _head_in(monkeypatch, repo)
    assert fails == [], fails


def test_head_message_name_token_fails(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    repo = _fresh_root(tmp_path / "r", "older commit", _j("#810 fix (#150)\n\nThanks ", who, " for the report."))
    _mod_, fails = _head_in(monkeypatch, repo)
    tip = _git(repo, "rev-parse", "HEAD")
    assert fails == [f"personal name token in the queued message {tip[:12]}"], fails


def test_head_message_email_and_private_name_fail(tmp_path, monkeypatch) -> None:
    secret = _j("zq", "fixture", "alias")
    repo = _fresh_root(tmp_path / "r", _j("#810 fix\n\nmail ", "desk", "@", "mailhost.co", " on ", secret))
    _mod_, fails = _head_in(monkeypatch, repo, (secret,))
    tip = _git(repo, "rev-parse", "HEAD")[:12]
    assert f"email outside placeholder domains in the queued message {tip}" in fails, fails
    assert f"local home-user name in the queued message {tip}" in fails, fails


def test_head_message_runs_in_a_shallow_clone(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    src = _fresh_root(tmp_path / "src", "initial public import", _j("fix for ", who))
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", src.as_uri(), str(shallow))
    _mod_, fails = _head_in(monkeypatch, shallow)
    assert len(fails) == 1 and "personal name token" in fails[0], fails


def test_head_message_cli_exit_codes(tmp_path, monkeypatch, capsys) -> None:
    who = _j("W", "ibble")
    mod = _mod()
    clean = _fresh_root(tmp_path / "c", "#810 clean message")
    monkeypatch.setattr(mod, "mill_root", lambda: clean)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    assert mod.main(["--head-message"]) == 0
    dirty = _fresh_root(tmp_path / "d", _j("fix for ", who))
    monkeypatch.setattr(mod, "mill_root", lambda: dirty)
    assert mod.main(["--head-message"]) == 1
    out = capsys.readouterr().out
    assert who not in out


# Card 935 (F225): --commits A..B scans every commit a PR would bring to main
# (message, author/committer identity, added diff lines). Release branches land
# as merge commits, so each of those commits reaches main as written.


def _range_repo(tmp_path: Path, *messages: str, name: str = "builder", email: str | None = None) -> Path:
    """A two-or-more-commit repo with role noreply identities on every commit."""
    email = email or _NOREPLY
    path = tmp_path / "range"
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    for i, msg in enumerate(messages):
        (path / "f.txt").write_text(f"line-{i}\n", encoding="ascii")
        _git(path, "add", "f.txt")
        _git(
            path,
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email}",
            "commit",
            "-q",
            "-m",
            msg,
        )
    return path


def _commit_on(
    repo: Path,
    msg: str,
    *,
    name: str = "builder",
    email: str | None = None,
    content: str | None = None,
) -> str:
    email = email or _NOREPLY
    body = content if content is not None else msg
    (repo / "f.txt").write_text(body, encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(
        repo,
        "-c",
        f"user.name={name}",
        "-c",
        f"user.email={email}",
        "commit",
        "-q",
        "-m",
        msg,
    )
    return _git(repo, "rev-parse", "HEAD")


def _range_in(monkeypatch, repo: Path, rev_range: str, names: tuple[str, ...] = ()):
    mod = _mod()
    monkeypatch.setattr(mod, "mill_root", lambda: repo)
    return mod, mod.scan_commit_range(rev_range, mod._home_user_regexes(names))


def test_commit_range_clean_passes(tmp_path, monkeypatch) -> None:
    repo = _range_repo(tmp_path, "base change", "tip change for the pack")
    base = _git(repo, "rev-list", "--max-count=1", "--reverse", "HEAD")
    # base is the oldest; range base..HEAD is the tip only when two commits.
    # Use the parent of HEAD as the left side.
    parent = _git(repo, "rev-parse", "HEAD~1")
    _mod_, fails = _range_in(monkeypatch, repo, f"{parent}..HEAD")
    assert fails == [], fails


def test_commit_range_bad_message_fails(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    repo = _range_repo(tmp_path, "base change")
    parent = _git(repo, "rev-parse", "HEAD")
    rev = _commit_on(repo, _j("fix for ", who))
    _mod_, fails = _range_in(monkeypatch, repo, f"{parent}..HEAD")
    assert f"personal name token in git commit {rev[:12]}" in fails, fails


def test_commit_range_bad_author_email_fails(tmp_path, monkeypatch) -> None:
    repo = _range_repo(tmp_path, "base change")
    parent = _git(repo, "rev-parse", "HEAD")
    bad = _j("desk", "@", "mail-host.co")
    rev = _commit_on(repo, "plain tip", email=bad)
    _mod_, fails = _range_in(monkeypatch, repo, f"{parent}..HEAD")
    assert f"author email is not noreply in git commit {rev[:12]}" in fails, fails
    assert bad not in "\n".join(fails)


def test_commit_range_bad_author_name_fails(tmp_path, monkeypatch) -> None:
    who = _j("W", "ibble")
    repo = _range_repo(tmp_path, "base change")
    parent = _git(repo, "rev-parse", "HEAD")
    rev = _commit_on(repo, "plain tip", name=who)
    _mod_, fails = _range_in(monkeypatch, repo, f"{parent}..HEAD")
    assert f"author name is not a role identity in git commit {rev[:12]}" in fails, fails
    assert who not in "\n".join(fails)


def test_commit_range_bad_diff_line_fails(tmp_path, monkeypatch) -> None:
    repo = _range_repo(tmp_path, "base change")
    parent = _git(repo, "rev-parse", "HEAD")
    addr = _j("someone", "@", "corp", ".", "com")
    rev = _commit_on(repo, "add a contact line", content=_j("contact=", addr, "\n"))
    _mod_, fails = _range_in(monkeypatch, repo, f"{parent}..HEAD")
    assert f"email outside placeholder domains in git commit {rev[:12]} diff" in fails, fails
    assert addr not in "\n".join(fails)


def test_commit_range_cli_exit_codes(tmp_path, monkeypatch, capsys) -> None:
    who = _j("W", "ibble")
    mod = _mod()
    clean = _range_repo(tmp_path / "c", "base", "tip clean")
    parent = _git(clean, "rev-parse", "HEAD~1")
    monkeypatch.setattr(mod, "mill_root", lambda: clean)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    assert mod.main(["--commits", f"{parent}..HEAD"]) == 0
    dirty = _range_repo(tmp_path / "d", "base")
    dparent = _git(dirty, "rev-parse", "HEAD")
    _commit_on(dirty, _j("fix for ", who))
    monkeypatch.setattr(mod, "mill_root", lambda: dirty)
    assert mod.main(["--commits", f"{dparent}..HEAD"]) == 1
    out = capsys.readouterr().out
    assert who not in out


def test_identity_name_role_and_bot_pass() -> None:
    mod = _mod()
    for name in ("builder", "desk", "pyginapithon", "the-mill maintainers", "GitHub", "dependabot[bot]"):
        assert mod.identity_name_ok(name), name
    who = _j("W", "ibble")
    assert not mod.identity_name_ok(who)
    assert not mod.identity_name_ok("")
