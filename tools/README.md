# tools/

Human CLIs that are **not** mill-office. Mill stays office commands (MAIL/TODO/connect).

## bin/

| Command | What |
| --- | --- |
| `git-changes` | Pretty file list / patch between two git revs (default: last version -> HEAD) |

### Run

From any checkout of this repo (or put `tools/bin` on PATH):

```bash
# Unix / macOS / WSL / Git Bash
./tools/bin/git-changes
./tools/bin/git-changes --from v0.4.12 --to HEAD
./tools/bin/git-changes --patch > since.patch
```

```bat
REM Windows (cmd / PowerShell)
tools\bin\git-changes.cmd
tools\bin\git-changes.cmd --pretty --no-color
python -m tools.git_changes --names
```

TTY -> pretty table. Pipe/redirect -> `--names` (no color). Override with `--pretty` / `--patch` / `--stat`.

## glance.py

Time a Wall page cold (lab tool, not run by CI). Each run loads the page with the HTTP cache off, then records the JS, CSS and HTML bytes at first paint, the time from click to painted for the desk panel and each strip pane, and the scripts each step loads. The first run also saves each pane's text and a screenshot, so a before and an after report can be diffed. It only reads; it never logs in or posts. Needs `playwright` with a `chromium` build.

```bash
python tools/glance.py URL before --roster ROSTER_ID
python tools/glance.py URL after --roster ROSTER_ID --out glance-report --runs 3
```

Writes `glance-report/TAG.json` and `glance-report/shots/`.

## check_pr_text.py

Scan PR and issue text with the commit-message hygiene rules (address, home path, email). CI runs it from `.github/workflows/pr_text.yml` on every PR, issue, comment and review, and once a day over all of them. Run `file` on a body before you post it: GitHub keeps every revision of a body in its edit history.

```bash
python tools/check_pr_text.py file body.md
```

Exit 1 on a hit; the report names the field, line and kind, never the text.

## check_validator_pass.py

The Validator gate in the merge queue. CI runs it from `.github/workflows/validator.yml` as the `validator_pass` check. On `merge_group` it passes only when every PR in the queue entry has a `validator` success status on its head sha; on `pull_request` it reports that state and passes. Standard library only, read-only token.

## check_sql.py

Compare the pack's routines to the live book. Run it on the wall host. It reads mill config, skips `wipe.sql` and `tables.sql`, and prints names only. The match is case-sensitive.

```bash
python tools/check_sql.py
python tools/check_sql.py --sql path/to/agent_coord/server/sql
```

Exit 1 when a pack routine is missing. Extra live routines are listed and do not fail the check. It does not apply SQL.

## book_shape.py

Compare a book's schema with a fresh install (card 840). Build a fresh book with `migrate.ensure` on an empty database, then name both: the fresh one and the book to check, such as a throwaway copy of an office dump after ensure. It reads the information schema only (tables, columns and enum values, indexes, foreign keys, triggers, routine bodies) and prints part names, never rows.

```bash
python tools/book_shape.py FRESH_DB BOOK_DB
```

Exit 1 when a part differs that is not in `KNOWN_LIVE_DRIFT`. CI runs the same comparison on a 0.7.6 book upgraded by tip ensure (`tests/server/records/test_book_schema_parity_840.py`).

## check_doc_commands.py

Hold the docs to the CLI. It builds the mill parser (the one `mill COMMAND --help` prints from) and reads every `mill ...` command in the code spans and code blocks of README.md, docs/*.md, docs/protocol, docs/dev, docs/install, docs/requirements and the office skills. It fails on a command that is gone (`mill mail`), a flag the command does not take, a code-block command short of its positionals (`mill connected` with no roster), a literal outside a positional's choices, a `<project>` where the command takes a roster, a retired word (`mill_wait`), the same drift in the parser's own help text, and a command or flag `mill -h` lists that no doc names. Hidden commands and flags are not owed a doc. A line that names a form only to say it does not exist passes when it says so (no, not, never, retired); otherwise mark it `<!-- doc-commands: skip -->`.

```bash
python tools/check_doc_commands.py          # exit 0 clean, 1 on any mismatch
python tools/check_doc_commands.py --list   # every command, its positional count and flags
```

CI runs it in the `mill_cli_smoke` job (F90).

## check_repro.py

Prove the pack is byte-reproducible. Clones HEAD twice into temp dirs (umask `022`, then `002`, a second apart), builds each with `python -m build --no-isolation` and `SOURCE_DATE_EPOCH` = the commit time, and prints every sha256. With a `dist/` argument, both builds must also match it. The normalizing is in the build backend (`build_backend/mill_build.py`), not here. CI `build_pack` and release `verify` run it.

```bash
python tools/check_repro.py dist
```

Exit 1 when any sha256 differs or a build is not one wheel and one sdist.

## orphan_scan.py

Which `agent_coord` modules nothing imports. Use this before deleting a file that "looks unused."

```bash
python tools/orphan_scan.py
python tools/orphan_scan.py --root path/to/the-mill
```

One orphan per line: `module<TAB>repo-relative-path`. A count goes to stderr. Exit 0.

It starts from `pyproject.toml` console scripts (`mill`, `mill-hold`, `agent-coord`), every `tests/` import, and `python -m agent_coord...` strings. Importing a package counts that package's `__init__.py` imports. `from . import name` counts the submodule. A file loaded by path (`spec_from_file_location`) counts too.

`web/wall_ui_save/` is a snapshot and is not scanned.

A module can be an orphan and still be a stub you meant to keep. The scan does not decide keep or delete.

## probe_deleted_rows.py

Test-only. Makes a deleted todo row and a deleted score row live, on the calling desk's own `t-<8 hex>` fixture rows only, so the deleted state can be checked on events, activity between, and the Wall pill (#160). Run it as a child of the shell that started `mill connect`. Needs an office at 0.6.30 or later.

```bash
python tools/probe_deleted_rows.py run
python tools/probe_deleted_rows.py delete --type todo --id N
```

See [docs/dev/PROBE-DELETED-ROWS.md](../docs/dev/PROBE-DELETED-ROWS.md).
