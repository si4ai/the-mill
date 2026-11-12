"""Shipped docs and hint strings must not map mill note to card text (card 1125 / D7).

note sets progress, --eta, --started, --done-when, or rides --waiting-on.
Free text goes through replace-body. This check is an allow-list: any mill-note
mention not tied to one of those purposes fails, including unknown wording.
It scans every doc in pyproject data-files plus agent_coord hint, refusal, and
help strings (card 1170).
"""
from __future__ import annotations

import ast
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]

SCORE_OR_WAKE = re.compile(
    r"\b(?:score|wake-done)\b.{0,200}--note|--note.{0,200}\b(?:score|wake-done)\b",
    re.IGNORECASE | re.DOTALL,
)
FIELD_OR_ENGLISH = re.compile(
    r"""(?ix)
    \bnote\s+over\b
    |\bnote\s+right\s+of\b
    |\bnote\s+left\s+of\b
    |\bend\s+note\b
    |\bprocess\s+note\b
    |\bstatus\s+note\b
    |\boperator\s+note\b
    |\bthe\s+note\s+arrives\b
    |\bthe\s+note\s+says\b
    |\byour\s+note\s+as\b
    |\blast_note\b
    |\blast\s+note\b
    |\band\s+the\s+note\b
    |\bthe\s+note\b
    |\bjoin\s+note\b
    |\bnote\s+re-install\b
    |\bnote\s+the\s+biggest\s+risk\b
    |\bNotes\b
    |\bnoted\b
    |\bnoting\b
    """
)
SINK_INTO_NOTE = re.compile(
    r"""(?ix)
    in\s+its\s+own\s+(?:mill\s+)?note
    |send\s+the\s+note\s+in
    |detail/`?note`?
    |detail\s*/\s*`?note`?
    |\blink\s+in\s+.{0,40}\bnote
    |\bnote\s+why\b
    |\b`note`\s+why\b
    |\bnote\s+the\s+(?:lost\s+)?reason
    |\bnote\s+(?:just\s+)?its\b
    |\bnote\s+as\s+you\s+go
    |\bnote/comms
    |\bin\s+a\s+`note`
    |\bin\s+the\s+note\b
    |\binto\s+`?note`?
    |\bput\s+.{0,40}\bin\s+(?:a\s+|the\s+)?`?note`?
    |\bgoes\s+in\s+the\s+note
    |record\s+findings
    |findings\s+with\s+note
    |note\s+it\s+on\s+the\s+card
    |jot\s+.{0,40}\bin\s+`note`
    """
)
ALLOWED_TIE = re.compile(
    r"""(?ix)
    \bprogress\b
    |--eta\b
    |\bETA\b
    |--started\b
    |--done-when\b
    |\bdone-when\b
    |waiting[_-]on
    |--waiting-on
    """
)
REDIRECT = re.compile(
    r"""(?ix)
    replace-body
    |does\s+not\s+append
    |not\s+card\s+text
    |not\s+mail,\s+not\s+card
    |confuse\s+`note`
    |card\s+text\s+changes
    |text\s+`note`\s+is\s+refused
    |`--note`\s+and\s+(?:any\s+)?other
    |`--note`\s+does\s+not
    """
)
BACKTICK_OR_MILL = re.compile(r"(?i)`note`|mill\s+note\b")
BARE_NOTE = re.compile(r"(?<![A-Za-z_`])note(?![A-Za-z_])", re.IGNORECASE)
OTHER_CMDS = re.compile(
    r"(?i)(`(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark|todo|doing)`"
    r"|\b(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark)\b)"
)
HINTISH = re.compile(
    r"(?i)(`note`|mill\s+note\b|in\s+its\s+own\s+(?:mill\s+)?note|note:\s|--note\b|send the note)"
)
BARE_SINK_VERB = re.compile(
    r"(?i)\bnote\s+(why|the|its|as\s+you|in\s+detail)|/\s*note\b|\+\s*note\b|note;"
)


def is_field_or_english(line: str) -> bool:
    if FIELD_OR_ENGLISH.search(line):
        if BACKTICK_OR_MILL.search(line) or SINK_INTO_NOTE.search(line):
            return False
        return True
    return bool(re.search(r"(?i)\|\s*Notes\s*\|", line))


def is_command_list(line: str) -> bool:
    if SINK_INTO_NOTE.search(line):
        return False
    if not (BACKTICK_OR_MILL.search(line) or BARE_NOTE.search(line)):
        return False
    return bool(OTHER_CMDS.search(line))


def has_mention(line: str) -> bool:
    if is_field_or_english(line):
        return False
    if BACKTICK_OR_MILL.search(line) or SINK_INTO_NOTE.search(line):
        return True
    if BARE_NOTE.search(line) and OTHER_CMDS.search(line):
        return True
    if "|" in line and re.search(r"(?i)(?:^|\|)\s*`?note`?\s*(?:\||$)", line):
        return True
    return bool(BARE_NOTE.search(line) and BARE_SINK_VERB.search(line))



SINK_PURPOSE = re.compile(
    r"""(?ix)
    \brecord\s+(?:the\s+)?decision
    |\brecord\s+findings
    |\bfindings\b
    |\bhandoff\s+reason
    |\bclose-lost\b
    |\bnote\s+reason
    |\bcustomer\s+quote
    |\broot\s+cause
    |\bseverity\s+and\s+owner
    |\bdecision\s+text
    |write\s+the\s+summary
    |log\s+each
    |\|\s*triage\s*\|
    |\|\s*decision\s*\|
    """
)


def clauses(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|") or s.count("|") >= 2:
        return [c.strip() for c in s.strip("|").split("|") if c.strip()]
    return [c.strip() for c in re.split(r"(?<=\.)\s+|;\s+|,\s+and\s+", line) if c.strip()]


def is_command_spine(clause: str) -> bool:
    if SINK_INTO_NOTE.search(clause) or SINK_PURPOSE.search(clause):
        return False
    if not (BACKTICK_OR_MILL.search(clause) or BARE_NOTE.search(clause)):
        return False
    return bool(OTHER_CMDS.search(clause))


def _parenthetical_progress_only(clause: str) -> bool:
    """'progress' only in a trailing '(progress and context)' does not tie the clause."""
    if re.search(r"(?i)progress\s+via", clause):
        return False
    return bool(re.search(r"\([^)]*\bprogress\b[^)]*\)\s*\.?\s*$", clause))


def clause_allowed(clause: str) -> bool:
    if is_field_or_english(clause):
        return True
    if SINK_INTO_NOTE.search(clause) and not REDIRECT.search(clause):
        return False
    lowered = clause.lower()
    if "in its own mill note" in lowered or "in its own note" in lowered:
        return False
    if REDIRECT.search(clause):
        return True
    if ALLOWED_TIE.search(clause) and not _parenthetical_progress_only(clause):
        return True
    return False


def allowed(line: str) -> bool:
    if (
        SCORE_OR_WAKE.search(line)
        and not BACKTICK_OR_MILL.search(line)
        and not SINK_INTO_NOTE.search(line)
    ):
        return True
    if is_field_or_english(line) and not BACKTICK_OR_MILL.search(line):
        return True
    parts = clauses(line)
    if not parts:
        parts = [line]
    table = line.strip().startswith("|") or line.count("|") >= 2
    row_has_purpose = table and any(
        ALLOWED_TIE.search(c)
        and not SINK_INTO_NOTE.search(c)
        and not _parenthetical_progress_only(c)
        for c in parts
    )
    row_has_sink_purpose = bool(SINK_PURPOSE.search(line))
    def part_mentions(part: str) -> bool:
        if table and re.fullmatch(r"`?note`?", part.strip(), re.I):
            return True
        return has_mention(part)

    for part in parts:
        if is_field_or_english(part) or not part_mentions(part):
            continue
        if clause_allowed(part):
            continue
        if row_has_purpose and not SINK_INTO_NOTE.search(part) and not row_has_sink_purpose:
            continue
        if is_command_spine(part) and not row_has_sink_purpose:
            continue
        return False
    return True


def bad_lines(text: str) -> list[str]:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if has_mention(line) and not allowed(line):
            hits.append("%s: %s" % (i, line.strip()))
    return hits


def data_file_docs() -> list[pathlib.Path]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    files = data["tool"]["setuptools"]["data-files"]
    out: list[pathlib.Path] = []
    for _dest, paths in files.items():
        for rel in paths:
            p = ROOT / rel
            if p.suffix.lower() in {".md", ".txt", ".rst"} and p.is_file():
                out.append(p)
    return out


def hint_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    docstring_ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(
            n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)
        ) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstring_ids.add(id(first.value))
    out: list[tuple[int, str]] = []

    def add(node: ast.AST, value: object) -> None:
        if isinstance(value, str):
            out.append((getattr(node, "lineno", 0), value.replace("\n", " ")))

    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and id(n) not in docstring_ids
        ):
            add(n, n.value)
        if not isinstance(n, ast.Call):
            continue
        name = ""
        func = n.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name != "add_parser":
            continue
        cmd = None
        if n.args and isinstance(n.args[0], ast.Constant) and isinstance(
            n.args[0].value, str
        ):
            cmd = n.args[0].value
        help_node = None
        help_val = None
        for kw in n.keywords:
            if kw.arg == "help" and isinstance(kw.value, ast.Constant):
                help_node = kw.value
                help_val = kw.value.value
        if cmd is not None and isinstance(help_val, str):
            # Pair the subcommand name with its help so a note parser is a mention.
            add(help_node or n, "mill %s: %s" % (cmd, help_val))
    return out


def test_pyproject_lists_data_files():
    assert data_file_docs(), "pyproject data-files should list shipped docs"


def test_shipped_docs_do_not_map_note_to_card_text():
    failures = []
    for path in data_file_docs():
        rel = path.relative_to(ROOT).as_posix()
        for hit in bad_lines(path.read_text(encoding="utf-8")):
            failures.append("%s:%s" % (rel, hit))
    assert not failures, "note mapped to card text in shipped docs:\n" + "\n".join(
        failures
    )


def test_hint_strings_do_not_map_note_to_card_text():
    failures = []
    for path in sorted((ROOT / "agent_coord").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for lineno, text in hint_strings(path):
            if has_mention(text) and not allowed(text):
                failures.append("%s:%s: %s" % (rel, lineno, text.strip()))
    assert not failures, "note mapped to card text in hint strings:\n" + "\n".join(
        failures
    )


def test_scanner_is_allow_list():
    # Unknown wording fails by default (not a phrase blocklist).
    assert bad_lines("put long text in a room letter and note its mail id.")
    assert bad_lines("| synthesize / revise | `note` |")
    assert bad_lines("| findings | brief section / `note` |")
    assert bad_lines("close-lost | pass + note why")
    assert bad_lines("pass then note the lost reason")
    assert bad_lines(
        "- Replace source/wiki/CRM/Drive SoR - link in detail/note."
    )
    assert bad_lines(
        "note: --done-when goes alone; send the note in its own mill note. Nothing changed"
    )
    # Allowed purposes and redirects stay quiet.
    assert not bad_lines("| progress | `note` |")
    assert not bad_lines("| next step / progress | `note` |")
    assert not bad_lines("| blocked (review) | waiting_on + `send` / `note` |")
    assert not bad_lines("| deploy | `claim` -> `note` -> `pass` |")
    assert not bad_lines(
        "note: --done-when goes alone; send it by itself. "
        "Card text: mill replace-body todo ID TEXT. Nothing changed"
    )
    assert not bad_lines(
        "A progress token as text (`9/12`) sets `progress`. `--eta` sets eta. "
        "Card text changes with `mill replace-body todo ID TEXT`. `--note` does not append."
    )
    # Validator mutants that 676d311 let through (D7): flag unknown wording.
    assert bad_lines("| record the decision | `note` + `pass` |")
    assert bad_lines("| close-lost | `pass` + note reason |")
    assert bad_lines("Record findings with note.")
    assert bad_lines(
        "Use `note` to record findings, and `replace-body` only for the summary."
    )
    assert bad_lines("| findings | `note` |")
    assert bad_lines("- Log each call outcome with `mill note`.")
    assert bad_lines(
        'Write the summary with mill note sales/deal-42 "won on price".'
    )
    assert bad_lines("| hand off | `send` next owner; `note` the handoff reason |")
    assert bad_lines("Capture the reason: note it on the card.")
    assert bad_lines("| triage | `note` severity and owner |")
    assert bad_lines('mill note ROSTER NEED --note "decision text"')
    assert bad_lines("Add the customer quote via `note` (progress and context).")
    assert bad_lines("Jot the root cause in `note`.")
    assert bad_lines("| decision | note |")
    # D8 shapes must fail until the shipped strings are reworded.
    assert bad_lines("mill note: update a claimed card body/pct")
    assert bad_lines(
        "note: refused, nothing written: this note needs 10 characters and the card has 3 left "
        "of its 4096 (every note on a card shares one budget). Put the long text in a room letter "
        "(mill reply <mail_id> --body-file PATH) and note just its mail id here."
    )
    # Quiet after the reword, and purpose-tied rows.
    assert not bad_lines(
        "mill note: set progress, --eta, --started or --done-when (card text: mill replace-body)"
    )
    assert not bad_lines(
        "note: refused, nothing written: this note needs 10 characters and the card has 3 left "
        "of its 4096 (every note on a card shares one budget). Put the long text in a room letter "
        "(mill reply <mail_id> --body-file PATH) and put just its mail id in the card with "
        "mill replace-body todo ID TEXT."
    )
    assert not bad_lines("| progress | `note` 9/12 |")
    assert not bad_lines("`note --eta 2h` when it slips")
    assert not bad_lines("`mill note r n --started`")
    assert not bad_lines("Set acceptance with `note --done-when TEXT`.")
    assert not bad_lines("Card text: `mill replace-body todo ID TEXT`.")
    assert not bad_lines("See release notes.")
