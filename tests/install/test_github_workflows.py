"""GitHub Actions supply-chain rules as checks, not prose.

Every third-party action is pinned to a full commit SHA, no workflow uses
pull_request_target, no job runs on a self-hosted runner, every workflow sets
top-level permissions, and every job that scans history clones it in full.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.M)
SHA_REF_RE = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _code(p: Path) -> str:
    """Workflow text without comment lines (comments may name banned words)."""
    return "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))


def _workflows() -> list[Path]:
    return sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))


def test_workflows_exist() -> None:
    names = {p.name for p in _workflows()}
    assert {"ci.yml", "release.yml", "codeql.yml"} <= names, names


def test_actions_pinned_to_full_sha() -> None:
    bad = []
    for p in _workflows():
        for ref in USES_RE.findall(p.read_text(encoding="utf-8")):
            if ref.startswith("./"):
                continue
            if not SHA_REF_RE.match(ref):
                bad.append(f"{p.name}: {ref}")
    assert not bad, bad


def test_no_pull_request_target_or_self_hosted() -> None:
    for p in _workflows():
        text = _code(p)
        assert "pull_request_target" not in text, p.name
        assert "self-hosted" not in text, p.name


def test_top_level_permissions_set() -> None:
    for p in _workflows():
        text = p.read_text(encoding="utf-8")
        assert re.search(r"^permissions:", text, re.M), p.name


def _job(text: str, name: str) -> str:
    body = text.split(f"\n  {name}:\n", 1)[1]
    nxt = re.search(r"\n  [a-z_]+:\n", body)
    return body[: nxt.start()] if nxt else body


def test_history_jobs_clone_full_history() -> None:
    """check_pack and both pytest jobs scan commit messages; shallow fails closed."""
    text = (WF / "ci.yml").read_text(encoding="utf-8")
    for name in ("check_pack", "pytest_no_sql", "pytest_sql"):
        job = _job(text, name)
        assert job.count("fetch-depth: 0") == job.count("actions/checkout@"), name
        assert "fetch-depth: 0" in job, name


def test_publish_jobs_use_oidc_not_tokens() -> None:
    """No stored publish token. The only secret is the #339 private-name list."""
    text = _code(WF / "release.yml")
    assert "id-token: write" in text
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"MILL_PRIVATE_NAMES"}
    assert "secrets." not in _job(text, "publish_pypi")
    assert "password:" not in text


def _on(text: str) -> str:
    """The top-level on: block of a workflow."""
    return text.split("\non:\n", 1)[1].split("\n\n", 1)[0]


def test_release_runs_only_on_v_tags_or_by_hand() -> None:
    """S-9: a push to main or a PR never starts release.yml."""
    on = _on((WF / "release.yml").read_text(encoding="utf-8"))
    assert re.search(r'^  push:\n    tags: \["v\*"\]$', on, re.M), on
    assert "branches" not in on and "pull_request" not in on and "schedule" not in on
    assert set(re.findall(r"^  (\w+):", on, re.M)) == {"push", "workflow_dispatch"}


def test_publish_jobs_are_gated_by_environment_and_event() -> None:
    text = _code(WF / "release.yml")
    pypi = _job(text, "publish_pypi")
    assert "name: pypi" in pypi and "startsWith(github.ref, 'refs/tags/v')" in pypi
    assert "testpypi" not in text.casefold() and "test.pypi.org" not in text
    jobs = set(re.findall(r"^  (\w+):\n    ", text.split("\njobs:\n", 1)[1], re.M))
    assert jobs == {"ci", "verify", "publish_pypi"}, jobs


def test_publish_job_is_oidc_in_pypi_env_with_pinned_action() -> None:
    pypi = _job(_code(WF / "release.yml"), "publish_pypi")
    assert "id-token: write" in pypi and "name: pypi" in pypi
    assert re.search(r"uses: pypa/gh-action-pypi-publish@[0-9a-f]{40}", pypi), pypi
    assert "password" not in pypi and "secrets." not in pypi and "repository-url" not in pypi


def test_ci_and_codeql_never_publish() -> None:
    for name in ("ci.yml", "codeql.yml"):
        text = _code(WF / name)
        assert "id-token: write" not in text, name
        assert "pypi-publish" not in text and "twine upload" not in text, name


def test_tree_hygiene_runs_wherever_check_pack_runs() -> None:
    """S-11: whole-tree hygiene drift fails CI, not only the local hook."""
    ci = _job((WF / "ci.yml").read_text(encoding="utf-8"), "check_pack")
    verify = _job((WF / "release.yml").read_text(encoding="utf-8"), "verify")
    for name, job in (("ci check_pack", ci), ("release verify", verify)):
        assert "python tools/check_pack.py dist" in job, name
        assert "python tools/precommit_hygiene.py tree" in job, name


# #634: no PyPI vector. Everything CI installs from an index is hash-checked,
# so a CA or mirror compromise cannot swap a package into a run that release.yml
# gates on, and the publish job is the only one that can mint an OIDC token.
LOCK = ROOT / "tools" / "ci-lock"
PIP_BOOTSTRAP_RE = re.compile(
    r'^python -m pip install "pip @ https://files\.pythonhosted\.org/packages/[0-9a-f/]+/'
    r'pip-[0-9.]+-py3-none-any\.whl#sha256=[0-9a-f]{64}"$'
)
LOCAL_DIST_RE = re.compile(r"^python -m pip install --no-deps --no-build-isolation dist/the_mill-\*\.(tar\.gz|whl)$")
LOCK_INSTALL_RE = re.compile(r"^python -m pip install --require-hashes( --no-deps)? -r tools/ci-lock/([\w-]+\.txt)$")


def _run_lines(p: Path) -> list[str]:
    """Shell lines of every run: step, with backslash continuations joined."""
    out: list[str] = []
    lines = _code(p).splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:- )?run: ?(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        body: list[str] = []
        if rest in ("|", ">", "|-", ">-"):
            i += 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append(lines[i].strip())
                i += 1
        else:
            body.append(rest)
            i += 1
        joined, cur = [], ""
        for ln in body:
            if ln.endswith("\\"):
                cur += ln[:-1].strip() + " "
                continue
            joined.append((cur + ln).strip())
            cur = ""
        out.extend(x for x in joined if x)
    return out


def _lock_reqs(path: Path) -> list[str]:
    """Requirement entries of a lock file, continuations joined."""
    entries, cur = [], ""
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        cur += s.rstrip("\\").strip() + " "
        if not s.endswith("\\"):
            entries.append(cur.strip())
            cur = ""
    return entries


def test_every_pip_install_in_workflows_is_hash_checked() -> None:
    """Only three install shapes: the hash-pinned pip wheel, a hashed lock, a local dist."""
    bad, seen_locks = [], set()
    for p in _workflows():
        for line in _run_lines(p):
            if re.search(r"\b(pip3?|uv|pipx|easy_install)\b.*\binstall\b", line):
                m = LOCK_INSTALL_RE.match(line)
                if m:
                    seen_locks.add(m.group(2))
                elif not (PIP_BOOTSTRAP_RE.match(line) or LOCAL_DIST_RE.match(line)):
                    bad.append(f"{p.name}: {line}")
            if re.search(r"\bpython -m build\b", line) and "--no-isolation" not in line:
                bad.append(f"{p.name}: isolated build fetches an unhashed backend: {line}")
    assert not bad, bad
    for name in seen_locks:
        assert (LOCK / name).is_file(), name


def test_ci_locks_are_fully_hashed_and_pinned() -> None:
    locks = sorted(LOCK.glob("*.txt"))
    assert {p.name for p in locks} >= {"build.txt", "ci.txt", "desk.txt"}, locks
    for p in locks:
        reqs = _lock_reqs(p)
        assert reqs, p.name
        for r in reqs:
            assert re.match(r"^[A-Za-z0-9._-]+(\[[\w,-]+\])?==[\w.+!-]+ ", r), (p.name, r)
            assert re.search(r"--hash=sha256:[0-9a-f]{64}", r), (p.name, r)


def test_ci_lock_runtime_lines_match_pyproject() -> None:
    """ci.in carries the pack's runtime deps verbatim, so CI tests what users resolve."""
    import tomllib

    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    lines = [ln.strip() for ln in (LOCK / "ci.in").read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    assert lines[: len(deps)] == deps, (lines, deps)


def test_runtime_dependencies_have_floors() -> None:
    """Every runtime dep names a >= floor; CI audits those floors (pack-floors.txt)."""
    import tomllib

    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    for d in deps:
        assert re.match(r"^[A-Za-z0-9._-]+(\[[\w,-]+\])?>=[0-9][\w.]*$", d), d
    ci = _job((WF / "ci.yml").read_text(encoding="utf-8"), "check_pack")
    assert "pip-audit --disable-pip --no-deps -r pack-floors.txt" in ci, ci
    assert "pip-audit --disable-pip --require-hashes -r tools/ci-lock/ci.txt" in ci, ci


def test_build_is_hash_locked_and_dated_by_commit() -> None:
    build = _job((WF / "ci.yml").read_text(encoding="utf-8"), "build_pack")
    assert "python -m pip install --require-hashes -r tools/ci-lock/build.txt" in build, build
    assert "--no-isolation" in build and "SOURCE_DATE_EPOCH" in build, build


def _perm_block(text: str) -> dict[str, str]:
    """permissions: mapping right under the given text start (or {} for the inline form)."""
    m = re.search(r"^( *)permissions:(.*)$", text, re.M)
    if not m:
        return {"<missing>": "<missing>"}
    if m.group(2).strip() == "{}":
        return {}
    if m.group(2).strip():
        return {"<scalar>": m.group(2).strip()}
    ind, out = len(m.group(1)), {}
    for ln in text[m.end():].splitlines()[1:]:
        if not ln.strip():
            continue
        if len(ln) - len(ln.lstrip()) <= ind:
            break
        k, _, v = ln.strip().partition(":")
        out[k.strip()] = v.strip()
    return out


def test_permissions_are_minimal() -> None:
    """Top level read-only (release: none); id-token: write only in publish_pypi."""
    allowed_write = {("release.yml", "publish_pypi"): {"id-token": "write"},
                     ("codeql.yml", "analyze"): {"contents": "read", "security-events": "write"},
                     ("pr_text.yml", "sweep"): {"contents": "read", "issues": "read", "pull-requests": "read"},
                     ("validator.yml", "validator_pass"): {"contents": "read", "pull-requests": "read", "statuses": "read"}}
    for p in _workflows():
        text = _code(p)
        top = _perm_block(text.split("\njobs:\n", 1)[0])
        assert top == ({} if p.name == "release.yml" else {"contents": "read"}), (p.name, top)
        body = text.split("\njobs:\n", 1)[1]
        for job in re.findall(r"^  ([\w-]+):\n", body, re.M):
            jb = _job("\n" + body, job)
            perms = _perm_block(jb) if re.search(r"^    permissions:", jb, re.M) else None
            want = allowed_write.get((p.name, job))
            if want is not None:
                assert perms == want, (p.name, job, perms)
            elif perms is not None:
                assert perms == {"contents": "read"}, (p.name, job, perms)
        if p.name != "release.yml":
            assert "id-token" not in text, p.name
    assert _code(WF / "release.yml").count("id-token: write") == 1


def test_pack_rebuilds_byte_identical_in_ci_and_release() -> None:
    """F78: CI and release verify rebuild the commit and compare sha256 with dist/."""
    ci = _job((WF / "ci.yml").read_text(encoding="utf-8"), "build_pack")
    assert ci.index("python -m build --no-isolation") < ci.index("python tools/check_repro.py dist"), ci
    assert ci.index("python tools/check_repro.py dist") < ci.index("actions/upload-artifact@"), ci
    verify = _job((WF / "release.yml").read_text(encoding="utf-8"), "verify")
    for name, job in (("ci build_pack", ci), ("release verify", verify)):
        assert "python tools/check_repro.py dist" in job, name
    # verify rebuilds in the ci.txt env, so it must pin the build tools build.txt pins.
    build = {e.split(" ")[0] for e in _lock_reqs(LOCK / "build.txt")}
    ci_pins = {e.split(" ")[0] for e in _lock_reqs(LOCK / "ci.txt")}
    assert build <= ci_pins, build - ci_pins


def test_pack_uses_the_reproducible_backend_and_spdx_license() -> None:
    """F78: the in-tree backend normalizes both archives; the license is SPDX."""
    import tomllib

    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert py["build-system"]["build-backend"] == "mill_build"
    assert py["build-system"]["backend-path"] == ["build_backend"]
    assert py["project"]["license"] == "MIT"
    assert py["project"]["license-files"] == ["LICENSE"]
    assert "include build_backend/mill_build.py" in (ROOT / "MANIFEST.in").read_text(encoding="utf-8")


def test_no_expression_in_any_run_line() -> None:
    """F94: event text (PR title, body, comments) is untrusted. No run: line in
    any workflow expands a ${{ }} expression; values reach a shell only by env."""
    bad = [f"{p.name}: {ln}" for p in _workflows() for ln in _run_lines(p) if "${{" in ln]
    assert not bad, bad


def test_pr_text_scans_every_posted_text_read_only() -> None:
    """F94: PR and issue title, body and comments are scanned when posted and daily."""
    text = (WF / "pr_text.yml").read_text(encoding="utf-8")
    on = _on(text)
    assert "pull_request:\n    types: [opened, edited, synchronize, reopened]" in on, on
    for ev in ("issues:", "issue_comment:", "schedule:", "workflow_dispatch:"):
        assert f"\n  {ev}" in on, ev
    code = _code(WF / "pr_text.yml")
    assert "secrets." not in code and "write" not in code
    assert re.search(r"github\.event\.[\w.]*(title|body)", code) is None
    assert "python3 tools/check_pr_text.py event" in _job(code, "event")
    assert "python3 tools/check_pr_text.py sweep" in _job(code, "sweep")
    assert "pip" not in code



def test_pr_text_never_runs_on_a_review_event() -> None:
    """F122 (#823): a review by a bot (Copilot's automatic review, even one that
    fails on quota) starts a pr_text run GitHub holds at action_required until a
    maintainer approves it. A bot review must never hold or delay a merge, so no
    workflow runs on a review event; the sweep reads review text instead."""
    for p in _workflows():
        on = _on(p.read_text(encoding="utf-8"))
        for ev in ("pull_request_review:", "pull_request_review_comment:"):
            assert f"\n  {ev}" not in on, f"{p.name} runs on {ev}"

def _on_block(text: str) -> str:
    return text.split("\non:\n", 1)[1].split("\n\n", 1)[0]


def test_required_workflows_run_in_the_merge_queue() -> None:
    """#810 (F109): ci and codeql hold the required checks on main, so both
    must run on merge_group or a merge queue waits on them forever."""
    for name in ("ci.yml", "codeql.yml"):
        assert re.search(r"^  merge_group:", _on_block(_code(WF / name)), re.M), name


def test_check_pack_scans_the_queued_squash_message() -> None:
    """#810 (F109): in the merge queue HEAD is the squash commit GitHub will
    put on main, so check_pack scans that one message before it lands."""
    job = _job(_code(WF / "ci.yml"), "check_pack")
    m = re.search(r"- if: github\.event_name == 'merge_group'\n(?:\s+\S.*\n)*?\s+run: python tools/check_pack\.py --head-message\n", job)
    assert m, "check_pack job lacks the merge_group --head-message step"


def test_validator_pass_runs_in_the_queue_outside_ci() -> None:
    """#810 (F110): validator_pass runs on merge_group and pull_request, in its
    own workflow (release.yml calls ci.yml with contents read only)."""
    code = _code(WF / "validator.yml")
    on = _on_block(code)
    assert re.search(r"^  merge_group:", on, re.M) and re.search(r"^  pull_request:", on, re.M), on
    assert "python3 tools/check_validator_pass.py" in _job(code, "validator_pass")
    assert "secrets." not in code and "pip" not in code
    assert "validator_pass" not in _code(WF / "ci.yml")


def test_ci_service_images_are_digest_pinned() -> None:
    """#763: every `services:` image in a workflow carries @sha256:<64 hex>."""
    pin = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
    bad: list[str] = []
    for path in _workflows():
        lines = _code(path).splitlines()
        in_services = False
        services_indent = 0
        for i, ln in enumerate(lines, 1):
            stripped = ln.lstrip(" ")
            indent = len(ln) - len(stripped)
            if re.match(r"services:\s*$", stripped):
                in_services = True
                services_indent = indent
                continue
            if in_services and stripped and indent <= services_indent and not stripped.startswith("#"):
                in_services = False
            if not in_services:
                continue
            m = re.match(r"image:\s*(\S+)\s*$", stripped)
            if not m:
                continue
            image = m.group(1).strip("\"'")
            if not pin.match(image):
                bad.append("%s:%d %s" % (path.name, i, image))
    assert bad == [], "service image missing digest pin: %s" % bad


def test_ci_mysql_service_matches_dependabot_docker_pin() -> None:
    """#763: the Dockerfile Dependabot watches names the same mysql pin as ci.yml."""
    ci = (WF / "ci.yml").read_text(encoding="utf-8")
    m = re.search(r"^\s+image:\s*(mysql:\S+)\s*$", ci, re.M)
    assert m, "ci.yml pytest_sql mysql image missing"
    image = m.group(1)
    assert "@sha256:" in image, image
    df = ROOT / ".github" / "docker" / "mysql" / "Dockerfile"
    assert df.is_file(), "missing Dependabot docker pin Dockerfile"
    assert ("FROM " + image) in df.read_text(encoding="utf-8"), (image, df.read_text(encoding="utf-8"))
    dep = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: docker" in dep
    assert "directory: /.github/docker/mysql" in dep
