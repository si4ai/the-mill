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
    |\ba\s+note\s+that\b
    |\bappends\s+a\s+note\b
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



# A command spine is allowed only when the note token has no object:
# claim -> note -> pass, or note followed by an allowed tie / -> / / / | / end.
# A phrase blocklist of known mutants is not the guard.
NOTE_TOKEN = re.compile(
    r"(?i)(?:`mill\s+note`|mill\s+note\b|`note`|(?<![A-Za-z_`-])note(?![A-Za-z_]))"
)
# Separators and other command tokens after note are not an object
# (`note`, `pass` or `claim` + `note` + `hold`).
SEP_TOKEN = re.compile(
    r"""(?x)
    \s*
    (?:
        \*\*
        |->
        |\u2192
        |/\s*drop\b
        |[(),+/|'"`]
        |\band\b
        |\.\.\.
    )
    """
)
QUOTED_ATOM = re.compile(r"\s*'[A-Za-z][A-Za-z0-9_-]*'")
CMD_FOLLOW = re.compile(
    r"(?i)\s*"
    r"(?:`(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark|todo|doing)`"
    r"|\b(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark)\b"
    r"|`note`|(?<![A-Za-z_`-])note(?![A-Za-z_]))"
)
TIE_OR_END = re.compile(
    r"""(?ix)
    \s*
    (?:
        $
        |[.,;:)"'\]]+\s*$
        |->
        |\u2192
        |/
        |\|
        |progress\b
        |--eta\b
        |\bETA\b
        |--started\b
        |--done-when\b
        |\bdone-when\b
        |waiting[_-]on
        |--waiting-on
        |--full\b
        |--doing\b
    )
    """
)
# A sibling table cell that is itself an imperative to put content in the note
# ("record the decision") is an implied object; this is a verb check, not a
# phrase blocklist of mutants.
SIBLING_SINK = re.compile(
    r"(?ix)^\s*(?:\*\*)?(?:record|write|log|capture|jot|store|paste|document)\b"
)


def clauses(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|") or s.count("|") >= 2:
        return [c.strip() for c in s.strip("|").split("|") if c.strip()]
    return [c.strip() for c in re.split(r"(?<=\.)\s+|;\s+|,\s+and\s+", line) if c.strip()]


# A value-taking flag may take one value (`--eta 2h`, `--done-when TEXT`).
# flagless ties and --started take no value. A value must not start with "-",
# so "->" is not swallowed. Values are consumed only after a value-taking
# flag, so they cannot hide a later object.
TIE_FLAG_VALUE = re.compile(
    r"""(?ix)
    \s*
    (?:
        --eta\b
        |--done-when\b
        |--waiting-on
        |--full\b
        |--doing\b
    )
    """
)
TIE_FLAG_BARE = re.compile(
    r"""(?ix)
    \s*
    (?:
        --started\b
        |progress\b
        |\bETA\b
        |\bdone-when\b
        |waiting[_-]on
    )
    """
)
FLAG_VALUE = re.compile(
    r"""(?x)
    \s+
    (?:
        "[^"]*"
        |'[^']*'
        |`[^`]+`
        |[A-Za-z0-9_./:][A-Za-z0-9_./:-]*
    )
    """
)
# Progress percentage after usage args (`mill note r n 40%`), not a bare `note` 75%.
PROGRESS_AFTER_USAGE = re.compile(r"\s+\d+%")
# explanatory adjunct after a consumed tie or flag, not a following object.
TRAILER = re.compile(r"(?ix)\s+(?:when|if|unless|after|before|sets|updates)\b")
# A table cell whose only object is a progress token (`note` 9/12).
NOTE_PROGRESS_VALUE = re.compile(
    r"(?i)(?:`mill\s+note`|mill\s+note\b|`note`|(?<![A-Za-z_`-])note(?![A-Za-z_]))\s+\d+(?:/\d+|%)\s*$"
)
TIE_END = re.compile(r"""\s*(?:$|[.,;:)"'`\]]+\s*$)""")
# Usage placeholders in a command synopsis, not card text.
USAGE_ARG = re.compile(
    r"""(?ix)
    \s*
    (?:
        <[^>]+>
        |\[[^\]]+\]
        |\bROSTER\b
        |\bNEED\b
        |\bID\b
        |\bTEXT\b
        |\bWHAT\b
        |(?<![A-Za-z])[rni](?![A-Za-z])
    )
    """
)
STMT_BREAK = re.compile(r"\s*[;]\s+")
ARROW_NEXT = re.compile(r"\s*(?:->|\u2192)")
NOTE_DEFINITION = re.compile(r"\s*:\s*")
ADVERBIAL = re.compile(r"(?i)\s+as\s+you\s+go")
RE_CMD_FOLLOW = re.compile(
    r"(?i)\s*(?:re-)?"
    r"(?:`(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark|todo|doing)`"
    r"|\b(?:create\s+todo|claim|unclaim|assign|send|reply|inbox|hold|drop|pass|unpark|mark)\b"
    r"|`note`|(?<![A-Za-z_`-])note(?![A-Za-z_]))"
)


def _followers_are_spine(rest: str) -> bool:
    """True when note is followed only by separators, another command, a tie, or end.

    A tie or flag after note does not hide a following object: consume the
    tie (and an optional value only after a value-taking flag) and keep
    inspecting the rest. An arrow starts the next pipeline step. A slash
    or quoted object is still inspected.
    """
    s = rest
    progressed = True
    saw_sep = False
    saw_usage = False
    saw_tie = False
    while s and progressed:
        progressed = False
        if TIE_END.match(s):
            return True
        if STMT_BREAK.match(s):
            return True
        if ARROW_NEXT.match(s):
            return True
        m = ADVERBIAL.match(s)
        if m:
            s = s[m.end():]
            progressed = True
            continue
        m = NOTE_DEFINITION.match(s)
        if m:
            after = s[m.end():]
            if ALLOWED_TIE.search(after) or REDIRECT.search(after):
                return True
            s = after
            progressed = True
            continue
        if saw_sep:
            m = QUOTED_ATOM.match(s)
            if m:
                s = s[m.end():]
                progressed = True
                continue
        m = SEP_TOKEN.match(s)
        if m:
            s = s[m.end():]
            saw_sep = True
            progressed = True
            continue
        m = USAGE_ARG.match(s)
        if m:
            s = s[m.end():]
            saw_usage = True
            progressed = True
            continue
        if saw_usage:
            m = PROGRESS_AFTER_USAGE.match(s)
            if m:
                s = s[m.end():]
                saw_tie = True
                progressed = True
                continue
        m = TIE_FLAG_VALUE.match(s)
        if m:
            s = s[m.end():]
            v = FLAG_VALUE.match(s)
            if v:
                s = s[v.end():]
            saw_tie = True
            progressed = True
            continue
        m = TIE_FLAG_BARE.match(s)
        if m:
            s = s[m.end():]
            saw_tie = True
            progressed = True
            continue
        if saw_tie and TRAILER.match(s):
            return True
        # A usage synopsis may continue with purpose flags or "progress token".
        if saw_usage and ALLOWED_TIE.search(s):
            return True
        m = RE_CMD_FOLLOW.match(s) or CMD_FOLLOW.match(s)
        if m:
            return True
    return not s.strip() or bool(TIE_END.match(s))


def _note_tokens_have_no_object(clause: str) -> bool:
    found = False
    for match in NOTE_TOKEN.finditer(clause):
        if not _followers_are_spine(clause[match.end():]):
            return False
        found = True
    return found


def is_command_spine(clause: str) -> bool:
    """True when note is a bare step among other commands, with no object."""
    if SINK_INTO_NOTE.search(clause):
        return False
    if not (BACKTICK_OR_MILL.search(clause) or BARE_NOTE.search(clause)):
        return False
    if not OTHER_CMDS.search(clause):
        return False
    return _note_tokens_have_no_object(clause)


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
        # A purpose token in the clause does not hide an object after note.
        if NOTE_TOKEN.search(clause):
            return _note_tokens_have_no_object(clause)
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
        # A purpose token in the same cell as a note object does not
        # bless that object. A sibling purpose cell may bless a bare
        # note (or note plus a progress token), not a text object.
        and (
            not has_mention(c)
            or clause_allowed(c)
            or (NOTE_TOKEN.search(c) and _note_tokens_have_no_object(c))
        )
        for c in parts
    )
    def part_mentions(part: str) -> bool:
        if table and re.fullmatch(r"`?note`?", part.strip(), re.I):
            return True
        return has_mention(part)

    for part in parts:
        if is_field_or_english(part) or not part_mentions(part):
            continue
        if clause_allowed(part):
            continue
        if (
            row_has_purpose
            and not SINK_INTO_NOTE.search(part)
            and (
                _note_tokens_have_no_object(part)
                or bool(NOTE_PROGRESS_VALUE.search(part))
            )
        ):
            continue
        if is_command_spine(part):
            if table and any(SIBLING_SINK.search(c) for c in parts if c != part):
                return False
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
    # D7: note with an object in a clause that also names another command (no purpose blocklist).
    assert bad_lines("| close-won | `pass` + `note` the customer's answer |")
    assert bad_lines("Use `pass` and `note` the customer's answer.")
    assert bad_lines("`claim` the card, `note` the vendor reply, then `pass`.")
    assert bad_lines("| escalate | `send` owner + `note` the incident summary |")
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
    # D12 / W2: a tie or flag after note must not hide a following object.
    assert bad_lines("`note` progress and the customer's answer")
    assert bad_lines("`claim` -> `note` progress and the customer's answer -> `pass`")
    assert bad_lines("| close | `pass` + `note` ETA plus the root cause |")
    assert bad_lines("`claim`, `note` --eta 2h and the vendor reply, `pass`.")
    assert bad_lines("`claim` + `note` / the decision text")
    assert bad_lines("`claim` + `note` 'decision' + `pass`")
    # Purpose-only ties without a following object stay quiet.
    assert not bad_lines("`note` --eta 2h")
    assert not bad_lines("`note` progress")
    assert not bad_lines("`claim` + `note` --eta 2h + `pass`")
    # D13: flagless ties and no-value flags must not eat "->"; trailers after a value stay quiet.
    assert not bad_lines("`claim` -> `note` progress -> `pass`")
    assert not bad_lines("`claim` -> `note` ETA -> `pass`")
    assert not bad_lines("| flow | `claim` -> `note` progress -> `pass` |")
    assert not bad_lines("`note` progress -> `pass --done`")
    assert not bad_lines("`note` --started -> `pass`")
    assert not bad_lines("`note` done-when -> `pass`")
    assert not bad_lines("`note` waiting_on -> `send`")
    assert not bad_lines("`note` --waiting-on -> `send`")
    assert not bad_lines("`note` --waiting-on desk when blocked.")
    assert not bad_lines("`note` --done-when TEXT sets the acceptance line.")
    # D14: a progress token after usage args is purpose use, not an object.
    assert not bad_lines("`mill note r n 40%` sets progress.")
    assert not bad_lines("`mill note ROSTER NEED 40%` sets progress.")
    # D15: a purpose sibling cell must not bless a note object in another cell.
    assert bad_lines("| close | `note` ETA | `note` the decision |")
