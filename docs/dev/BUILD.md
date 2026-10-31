# Build the mill pip pack

This is for people who **change mill** (the git tree). App users do not build - they `pip install the-mill`.

Do not pin mill versions in docs.

**Builds between releases.** The version number changes only at the bump, so a build from a later `main` sha still reports the last release (for example `0.7.8`) in replies and on the Wall. `mill --version` adds `+g<sha7>` when it can tell the commit: run from a git checkout (its HEAD), or installed with `pip install "git+https://github.com/si4ai/the-mill@<sha>"` (pip records the commit). A wheel, sdist or plain-folder install of a main sha prints the bare number, so record the sha you installed from. Regression row F61 (dev-version).

## Release order

Assume **regression tests already pass**. Then:

**Changelog rotation** (card 936): `CHANGELOG.md` at the repo root has exactly three sections, newest first: TBD (upcoming), New changes, Last changes. TBD carries the disclaimer that upcoming is the current plan, not a promise. At each release bump: move New into Last (drop the previous Last; git history and GitHub Releases keep it), move landed TBD items into New, and keep TBD for later plans. `check_pack` scans the file like any doc.


1. **Local hygiene** - bump version, `python -m build`, `python tools/check_pack.py dist`, `python tools/mill_cli_smoke.py` (install the **tarball** from a non-git cwd). Human pass on tracked `.md` / `.txt`. Do not push a dirty `dist/`.
2. **Commit** the version bump + hygiene fixes.
3. **Push** through a pull request on GitHub: `main` is protected by a ruleset, see [CONTRIBUTING-PR.md](CONTRIBUTING-PR.md).
4. **Pipeline** - wait for the GitHub Actions `ci` jobs `build_pack` -> `check_pack` -> `mill_cli_smoke` -> `pytest_no_sql` and `pytest_sql` (and pip-audit). `pytest_no_sql` installs Node.js 24.21.0 (the validators need Node `^22.22.0 || >=24.8.0`, the `engines` range in `tools/wall-validators/package.json`; html-validate uses `fs.globSync`, and `npm ci` refuses an older Node there, so run the wall tests locally on Node 22.22+ or 24.8+), runs `npm ci --prefix tools/wall-validators` so stylelint, eslint, and html-validate check the wall files, then runs `pytest tests -m "not sql"`. `pytest_sql` starts MySQL 8.4 beside the job and runs `pytest tests -m sql`, with `AGENT_COORD_HOST=mysql`. SQL suites use per-process throwaway DB names (`tests/sql_isolate.py`) so concurrent local runners cannot wipe a shared mill_records_test. PR and `main` runs do **not** publish.
5. **If pipeline GO** - after ship GO consensus at the exact sha (see [CI ship path](#ci-ship-path)), push an annotated tag `v<version>` on that sha (`git tag -a`). The tag starts `release.yml`, which reruns every `ci` job, then publishes the same wheel + sdist they scanned to PyPI through trusted publishing. See [CI ship path](#ci-ship-path).
6. **`mill update`** - from a **non-git cwd**: stop mill-wall and wait until it is STOPPED, then `pip install -U the-mill` (or `mill update`), then start mill-wall. Do not pip while mill-wall is still running (`sc stop` on Windows returns at STOP_PENDING; wait for STOPPED). Refuse the install when another process is `mill connect` holding `Scripts\mill.exe`; stop that connect first. The installer does not kill it. After pip, import the package and the ASGI app before starting mill-wall. If pip or that import fails, leave mill-wall stopped. `mill -V` is the installed mill. A live office book does not pick up new stored procedures from that recycle. `mill update` only flags them; apply them on the host with `mill install sql --apply` as in [HOST.md](../install/HOST.md#update-a-running-host). Wall serve + MySQL pool/gzip/cache and what recycle vs SQL apply means: [HOST.md mill-wall and MySQL](../install/HOST.md#mill-wall-and-mysql-operator-config). The pipeline does not touch a customer book. **Gate:** the A/B in [HOST.md](../install/HOST.md#stored-procedures) gates a live SQL apply (lan or aws); CI `pytest_sql` covers writing the SQL.
7. **skill.md** - copy the pack's `docs/protocol/skill.md` (`mill join` prints its path after `skill`) over the desk's mill-desk `SKILL.md`, then **restart the TUI**. `python tools/check_skill_copy.py PATH` exits 0 when that copy matches the source; CI runs it with `--installed` on the pack (regression row F33, skill-copy). `mill briefing skill` is a terminal rendering, not a copy. mill on PATH is not the skill.

Git mill on this checkout uses `PYTHONPATH` / `pack_local.py --install`, not `mill update` from the repo root. Never `pip install .` from the git tree.

## What you produce

From the repo root:

```
python -m pip install build
python -m build
```

That writes two files under `dist/`:

- `the_mill-<version>-py3-none-any.whl` - what most `pip install` users get
- `the_mill-<version>.tar.gz` - the source tarball (`pip` can unpack this too)

Neither file starts mill-wall or MySQL. They only install the mill package (`mill` on PATH). The pack includes FastAPI/uvicorn so mill-wall can run after `pip install`.

Use the tarball, not only the wheel. If the tarball is dirty, a source install is dirty.

## Reproducible pack

Two builds of the same commit give byte-identical wheel and sdist, so anyone can rebuild a release and compare sha256 with PyPI. Date the build by the commit:

```
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" python -m build --no-isolation
python tools/check_repro.py dist
```

Use the build tools pinned in `tools/ci-lock/build.txt` (setuptools, build) and Python 3.12, as CI does: another setuptools or zlib can write other bytes. The backend is `build_backend/mill_build.py` (`[build-system]` in `pyproject.toml`). It runs `setuptools.build_meta`, then rewrites both archives without touching member bytes:

- every member mtime and the sdist gzip header time are `SOURCE_DATE_EPOCH`, and the gzip header has no file name (setuptools dates only the wheel by it; the sdist kept checkout mtimes and the build time)
- sdist members are sorted by name, owner `0/0` with empty user and group names (it kept the builder's uid, gid and login)
- files are `0644` (`0755` with an execute bit), directories `0755`, in both archives (the checkout umask leaked in)
- a link or other special member in the sdist fails the build; the wheel keeps its member order

PKG-INFO, the data-files and the member order already came out the same. Without `SOURCE_DATE_EPOCH` the build still works, but member times stay the checkout times, so two builds differ. `tools/check_repro.py` clones HEAD twice into temp dirs under umask `022` and `002`, a second apart, builds each with the commit time, prints every sha256 and fails unless both builds (and `dist/`, when given) match. CI `build_pack` and release `verify` run it. Regression row F78 (sdist-repro).

The license is the SPDX form (`license = "MIT"`, `license-files = ["LICENSE"]`, setuptools 77 or later); the table form stops building after 2027-02-18.

## Local pack (no PyPI)

Office dogfood **without** steps 3-5. After a commit:

```
python tools/pack_local.py
python tools/pack_local.py --install --notify
```

`--install` pip-installs the tarball from a non-git cwd. `--notify` mails the build-validator desk a local-pack note (`mill send desk build-validator --roster the-mill --body-file FILE`): re-measure, dry-run only. Regression row F32 (pack-local-notify): `tests/tools/test_pack_local_notify.py` parses that command with the mill parser. Does not `twine upload`. Recycle mill-wall after `--install`. Still recopy skill.md if the briefing changed.

## What must not be in either artifact

`tools/check_pack.py` is fail-closed on both the wheel and the sdist. Unpack both and fail if you find:

- backups (`.bak`, `.bak-*`)
- bytecode (`__pycache__`, `.pyc`)
- `wall_ui_save/` (local Wall dumps; gitignored, must not ship)
- surprise binaries under `agent_coord/`
- home-path prefixes (`C:\Users\`, `C:/Users/`, `/Users/`, `/home/`)
- emails outside the placeholder domains (`example.com/.org/.net`, `.example`, `.test`, `.invalid`, `.localhost`, GitLab and GitHub noreply); the project local-part `pyginapithon` passes only on a noreply domain, and `git@` SSH remotes pass
- tokens
- office dest dumps or Wall diary scrapes
- a complete IP that is not a documentation address. Documentation ranges are RFC 5737 (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) and RFC 3849 (`2001:db8::/32`). Loopback (`127.0.0.0/8`, `::1`) and unspecified (`0.0.0.0`, `::`) may stay. LAN *prefix* `192.168.1.` / `192.168.1.%` / `192.168.1.*` is mill join product and is not a complete host. The same rule covers the wheel, the sdist, git-tracked files (including comments), and git commit messages
- a Windows editor mark in a text file in the wheel, the sdist, or git. Text means source and docs (`.py`, `.md`, `.sql`, `.js`, `.css`, `.html`, `.ps1`, `.sh`, `.toml`, `.yml`, `.json`, `.svg`, `.txt`, and the same kind of file). Images, fonts, and other binaries are not decoded for this scan. The mark is a leading byte-order mark (UTF-8 `EF BB BF`, or UTF-16 `FF FE` / `FE FF`) or one of these code points: U+FEFF, U+00A0, U+00B1, U+00B7, U+0394, U+200B, U+200C, U+200D, U+2013, U+2014, U+2018, U+2019, U+201C, U+201D, U+2026, U+2190 through U+2193, U+2264, U+2713. PowerShell `Set-Content -Encoding utf8` writes U+FEFF. The report is the code point and the path, not the glyph. The ASCII escape for U+FEFF may stay: that is how `mill send` strips a file-body mark. Old commit messages are not scanned for these marks
- `Sudoku` leftover under `agent_coord/`

The scanner reports *that* a home path, email, local home-user, or non-documentation address hit, not the matched substring.

**Local extra:** profile folder names from `C:\Users`, `/home` (Linux/WSL), `/Users` (macOS), and `wsl.exe ls /home` when check_pack runs on Windows with WSL. The same net includes the computer name and hyphenated office-alias filenames under the local mill home. A plain alias with no hyphen is not part of this net. Case-insensitive word-boundary scan of **wheel + sdist**, **`git ls-files`**, and commit messages. GitHub shows tracked `docs/dev/` even when not in the wheel. Documented prefixes (`C:\Users\`, `/home/`) in BUILD.md are allowed; a **login name**, computer name, or hyphenated office alias in a tracked file fails. Names are read from disk - not a word-list in `check_pack.py`. CI has no profile folders or aliases of ours (`CI=true` skips the disk read, so the runner login is not scanned). There the names come from the repository secret `MILL_PRIVATE_NAMES`: one name per line, passed to the `check_pack` step in env only, never echoed or written to a file, and never in the repo. CI fails closed when that list is empty, except a pull request from a fork (GitHub gives it no secrets): it prints that it skipped, and the push to `main` scans again. Dependabot runs read Dependabot secrets, so the same name is set there too. Off CI the variable is optional and adds to the names read from disk. Regression row F50 (ci-private-names). Skip Public / Default / Administrator / root / Guest / Shared. The address scan is not part of that skip. It runs on the wheel, the sdist, `git ls-files`, and commit messages in CI too.

`wall.local` in install/TLS copy is the product cert hostname. That stays.

`tests/` may appear in the tarball (repo/dev). They must not appear in the wheel. A `Sudoku` hit under `tests/` is a note, not a fail. A non-documentation address under `tests/` fails.

## Pack recipe (so junk cannot sneak back)

`pyproject.toml` must:

- include only product data: `static/*`, `schema.sql`, `scripts/*`, `wall_ui` `*.html` / `*.css` / `*.js` / `*.md`, and mill briefing markdown (`README.md`, `docs/JOIN.md`, `docs/HOST.md`, `docs/skills/**` (office adapters; not `docs/dev/`)
- exclude `__pycache__`, `*.pyc`, `*.bak`, `*.bak-*`, `*.orig`, `*~`
- prune `agent_coord/web/wall_ui_save` (`MANIFEST.in`)

Delete leftover backups and `__pycache__` from the tree **before** `python -m build`. The exclude list is backup; a dirty tree can still leak into the tarball.

## Pipeline hygiene

Three workflows live under `.github/workflows/`. Every action is pinned to a
full commit sha (the repo also requires sha pinning), no workflow uses
`pull_request_target`, no job runs on a self-hosted runner, and the default
`GITHUB_TOKEN` is read-only.

- `ci.yml` runs on every pull request, every push to `main`, and when
  `release.yml` calls it. It never publishes. Jobs:
  1. `build_pack` - `python -m build --no-isolation` from the hash-locked `tools/ci-lock/build.txt`, dated by the commit (`SOURCE_DATE_EPOCH`) -> `dist/`, then `python tools/check_repro.py dist` (two more builds must match byte for byte, see [Reproducible pack](#reproducible-pack)) -> uploaded as the `dist` artifact
  2. `check_pack` - `python tools/check_pack.py dist` (with the `MILL_PRIVATE_NAMES` secret, see What must not be in either artifact), then on `pull_request` `python tools/check_pack.py --commits origin/main..HEAD` (every commit's message, author/committer identity, and added diff lines; F225), then on `merge_group` `--head-message`, then `pip-audit` (no installs) on the runtime floors (`pack-floors.txt`) and on `tools/ci-lock/ci.txt`
  3. `mill_cli_smoke` - install the sdist, run `python tools/mill_cli_smoke.py` (`mill -V`, `mill connect --help`, no retired commands on `--help`, and the real-path rows in `RUN_ROWS`: `mill connect` runs its whole body against a closed local port and must reach the socket loop with no traceback), then `tools/check_skill_copy.py --installed`, then `tools/check_doc_commands.py` (every `mill` command, flag and positional the docs teach matches the parser, F90)
  4. `pytest_no_sql` and `pytest_sql` - the test suites (see step 4 of Release order)

  Every PyPI install in CI is hash-checked (#634): the pinned pip wheel, then
  `pip install --require-hashes -r tools/ci-lock/<lock>.txt`; the local
  `dist/` files install with `--no-deps --no-build-isolation` and `pip check`.
  `tools/ci-lock/README.md` has the regenerate command.

  `check_pack`, `pytest_no_sql` and `pytest_sql` check out full history
  (`fetch-depth: 0`): they scan commit messages, and a shallow clone fails
  closed (regression row S-8).
  `check_pack` also fails when any commit's author or committer email is not a GitHub noreply address (`<id>+<login>@users.noreply.github.com`) or GitHub's own web-flow committer; the report names the commit, never the address (regression row S-10). On a pull request the `--commits` scan also requires author and committer **names** to be a role identity (desk role, project account, `the-mill maintainers`, `GitHub`, or a `[bot]` name) and scans each commit's added lines with the same scrub and secret rules as the tip (F225). Release branches land on main with a merge commit after that check; normal PRs stay squash.
- `codeql.yml` runs CodeQL (`analyze (python)`, `analyze (actions)`) on pull
  requests, pushes to `main` and weekly.
- `release.yml` runs only on a pushed `v*` tag (PyPI) or a manual
  `workflow_dispatch` (a dry run: build and verify, no upload). A push to `main`
  never starts it.

The `ci` and CodeQL jobs above are the required status checks on `main`.

Same scanner locally (step 1 of Release order): `python tools/check_pack.py dist`.

## CI ship path

The release ships from GitHub Actions (`release.yml`), not from an office host,
and uses PyPI trusted publishing (OIDC). No PyPI token is stored anywhere.

1. The version bump is merged on `main` and `ci` on that sha is green.
2. Ship GO consensus on that exact sha: each desk your office assigns to the builder, validator and shipper roles sends GO naming the sha. A silent desk is not a GO; there is no timeout and no quorum. A NOGO blocks. When desks are unavailable or a NOGO is stuck, the human office owner judges and may override.
3. Push an annotated tag `v<version>` (same as `pyproject.toml`) on that sha: `git tag -a v<version> -m "the mill <version>" <sha>`, then `git push origin v<version>`. An annotated tag records who tagged and when; a lightweight tag does not. The tag ruleset lets only the repository admin create, move or delete `v*` tags.
4. `release.yml` calls `ci.yml` (every job above), then `verify` refuses unless `dist/` is exactly the `the_mill-<version>` wheel + sdist for the tag, `tools/check_pack.py dist` passes, `twine check --strict` passes, and `tools/check_repro.py dist` rebuilds the tagged commit twice to the same sha256 as `dist/`.
5. `publish_pypi` runs in the `pypi` environment, which accepts only `v*` tags and waits for a required-reviewer approval. Builder approves it through the GitHub API (`POST /repos/{owner}/{repo}/actions/runs/{run_id}/pending_deployments` with body `environment_ids` = [the `pypi` environment id], `state` = `approved`, and a `comment`), using the repo token from its env var, never printed. The human is not in the loop for mill releases; the reviewer gate exists only to stop a stray tag from publishing. It then uploads `dist/` with `pypa/gh-action-pypi-publish` using a short-lived OIDC token.
6. Hosts then update from PyPI as in step 6 of Release order.

Dry run: run `release.yml` by hand (`workflow_dispatch`). It runs every `ci` job and `verify` the same way and uploads nothing.

Setup, once per project (the human office owner):

- On PyPI, project `the-mill` -> Publishing -> add a trusted publisher (GitHub): owner `si4ai`, repository `the-mill`, workflow `release.yml`, environment `pypi`. The workflow file name and the environment name are part of the trust; renaming either breaks publishing.
- After the first trusted release, revoke any old PyPI API token for the project.
- GitHub environment `pypi` (required reviewer, deployment tags `v*`), and the `main` and `v*` rulesets. These are repo settings, not files.

A failed upload leaves PyPI unchanged for that file; fix and rerun the job. PyPI never accepts the same version twice, so a bad release needs a new version and tag.

## Allowlist vs gitignore

`.gitignore` is a denylist (skip these). The wheel allowlist is the opposite: only expected paths may ship. Changing the allowlist is a visible git diff. The pack pipeline is what enforces it.
