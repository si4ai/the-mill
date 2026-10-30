"""#811 (F111): validator_pass trusts only a `validator` status the Validator app posted.

Anyone with write access can post a commit status with context `validator`.
The gate counts only statuses whose creator login is the app's bot login;
every other creator is ignored, neither pass nor fail. The latest counted
status on the exact head sha decides. The API is a fake; every value is
invented except the app's bot login.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "example-org/the-mill"
BASE = "b" * 40
QHEAD = "c" * 40
HEAD = "2" * 40
OLD = "3" * 40
PR = 151
BOT = "si4ai-validator[bot]"
SEAT = "validator-seat"  # a person or PAT user, not the app


def _mod():
    spec = importlib.util.spec_from_file_location("check_validator_pass", ROOT / "tools" / "check_validator_pass.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _st(sha: str, state: str, login: str, sid: int, context: str = "validator",
        ctype: str | None = None) -> dict:
    # GitHub's user object: type "Bot" for an app's bot user, else "User".
    if ctype is None:
        ctype = "Bot" if login.endswith("[bot]") else "User"
    creator = {"login": login, "type": ctype} if ctype else {"login": login}
    return {"id": sid, "context": context, "state": state, "creator": creator,
            "url": f"https://api.github.com/repos/{REPO}/statuses/{sha}"}


def _fake(by_sha: dict[str, list[dict]]):
    """Statuses newest first, as GET /commits/{sha}/statuses lists them."""
    seen: list[str] = []

    def fetch(path: str):
        seen.append(path)
        if path == f"/repos/{REPO}/compare/{BASE}...{QHEAD}":
            return {"commits": [{"commit": {"message": f"#2 second (#{PR})"}}]}
        if path == f"/repos/{REPO}/pulls/{PR}":
            return {"number": PR, "head": {"sha": HEAD}}
        for sha, sts in by_sha.items():
            if path.startswith(f"/repos/{REPO}/commits/{sha}/statuses?"):
                page = int(path.rsplit("page=", 1)[1]) if "&page=" in path else 1
                return sts[(page - 1) * 100:page * 100]
            if path.startswith(f"/repos/{REPO}/commits/{sha}/status?"):
                # the combined status: latest per context, any creator, no creator check possible
                return {"statuses": [s for s in sts if s["context"] == "validator"][:1]}
        if "/commits/" in path:
            return [] if "/statuses?" in path else {"statuses": []}
        raise AssertionError(path)

    return fetch, seen


def _gate(by_sha):
    fetch, _ = _fake(by_sha)
    lines: list[str] = []
    ev = {"merge_group": {"head_ref": f"refs/heads/gh-readonly-queue/main/pr-{PR}-{BASE}",
                          "base_sha": BASE, "head_sha": QHEAD}}
    rc = _mod().run("merge_group", ev, REPO, fetch, out=lines.append)
    return rc, lines


def test_expected_login_is_one_named_constant() -> None:
    mod = _mod()
    assert mod.VALIDATOR_LOGIN == BOT
    assert (ROOT / "tools" / "check_validator_pass.py").read_text(encoding="utf-8").count(BOT) == 1


def test_pat_user_success_is_rejected() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "success", SEAT, 10)]})
    assert rc == 1, lines
    assert any(ln.startswith("FAIL") and f"PR #{PR}" in ln for ln in lines), lines


def test_bot_success_is_accepted() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "success", BOT, 10)]})
    assert rc == 0, lines


def test_bot_login_with_user_type_is_rejected() -> None:
    """The login alone is not enough: the creator type must be Bot (#663)."""
    rc, lines = _gate({HEAD: [_st(HEAD, "success", BOT, 10, ctype="User")]})
    assert rc == 1, lines
    assert any(ln.startswith("FAIL") and f"PR #{PR}" in ln for ln in lines), lines


def test_bot_login_without_a_creator_type_is_rejected() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "success", BOT, 10, ctype="")]})
    assert rc == 1, lines


def test_user_type_failure_over_a_bot_success_is_ignored() -> None:
    """A status with the bot login but type User neither passes nor fails."""
    rc, lines = _gate({HEAD: [_st(HEAD, "failure", BOT, 11, ctype="User"), _st(HEAD, "success", BOT, 10)]})
    assert rc == 0, lines


def test_bot_failure_after_other_user_success_fails() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "failure", BOT, 11), _st(HEAD, "success", SEAT, 10)]})
    assert rc == 1, lines


def test_other_user_success_after_bot_failure_still_fails() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "success", SEAT, 11), _st(HEAD, "failure", BOT, 10)]})
    assert rc == 1, lines


def test_other_user_success_after_bot_success_still_passes() -> None:
    # ignored, not a fail: a forged status neither passes nor blocks
    rc, lines = _gate({HEAD: [_st(HEAD, "failure", SEAT, 11), _st(HEAD, "success", BOT, 10)]})
    assert rc == 0, lines


def test_bot_success_on_a_different_sha_is_ignored() -> None:
    rc, lines = _gate({OLD: [_st(OLD, "success", BOT, 10)], HEAD: []})
    assert rc == 1, lines
    # a status listed for the head whose url names another sha does not count either
    rc, lines = _gate({HEAD: [_st(OLD, "success", BOT, 10)]})
    assert rc == 1, lines


def test_other_contexts_from_the_bot_do_not_count() -> None:
    rc, lines = _gate({HEAD: [_st(HEAD, "success", BOT, 10, context="validator/extra")]})
    assert rc == 1, lines


def test_forged_statuses_cannot_push_the_bot_status_off_the_first_page() -> None:
    spam = [_st(HEAD, "success", SEAT, 1000 - i) for i in range(150)]
    rc, lines = _gate({HEAD: spam + [_st(HEAD, "success", BOT, 10)]})
    assert rc == 0, lines


def _pr_stage(by_sha, env_summary: list[str] | None = None):
    fetch, _ = _fake(by_sha)
    lines: list[str] = []
    kw = {} if env_summary is None else {"summary": env_summary.append}
    rc = _mod().run("pull_request", {"pull_request": {"number": PR, "head": {"sha": HEAD}}}, REPO, fetch,
                    out=lines.append, **kw)
    return rc, lines


def test_pr_stage_without_a_verdict_says_waiting_not_pass() -> None:
    # a forged success is no verdict either
    summary: list[str] = []
    rc, lines = _pr_stage({HEAD: [_st(HEAD, "success", SEAT, 10)]}, summary)
    assert rc == 0, lines  # green: the PR must stay enqueue-able
    want = f"WAITING: no {BOT} verdict on {HEAD} yet (report only; merge queue enforces)"
    assert want in lines, lines
    assert f"::notice title=validator_pass waiting::{want}" in lines, lines
    assert not any(ln.startswith(("OK", "PASS")) for ln in lines), lines
    assert any(want in s for s in summary), summary


def test_pr_stage_names_a_failure_or_pending_verdict_as_waiting() -> None:
    for state in ("failure", "pending", "error"):
        rc, lines = _pr_stage({HEAD: [_st(HEAD, state, BOT, 10)]})
        assert rc == 0, lines
        want = f"WAITING: {BOT} verdict on {HEAD} is {state} (report only; merge queue enforces)"
        assert want in lines and f"::notice title=validator_pass waiting::{want}" in lines, lines


def test_pr_stage_with_a_bot_success_still_says_report_only() -> None:
    rc, lines = _pr_stage({HEAD: [_st(HEAD, "success", BOT, 10)]})
    assert rc == 0, lines
    want = f"REPORT: {BOT} success on {HEAD} (report only; merge queue enforces)"
    assert want in lines and f"::notice title=validator_pass report::{want}" in lines, lines


def test_main_writes_the_pr_stage_line_to_the_job_summary(tmp_path, monkeypatch) -> None:
    mod = _mod()
    ev = tmp_path / "event.json"
    ev.write_text('{"pull_request": {"number": %d, "head": {"sha": "%s"}}}' % (PR, HEAD), encoding="utf-8")
    summ = tmp_path / "summary.md"
    fetch, _ = _fake({HEAD: []})
    monkeypatch.setattr(mod, "http_fetch", fetch)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    assert mod.main() == 0
    assert f"WAITING: no {BOT} verdict on {HEAD} yet" in summ.read_text(encoding="utf-8")
