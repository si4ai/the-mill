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
    |\bnote\s+its\b
    |\bnote\s+as\s+you\s+go
    |\bnote/comms
    |\bin\s+a\s+`note`
    |\bin\s+the\s+note\b
    |\binto\s+`?note`?
    |\bput\s+.{0,40}\bin\s+(?:a\s+|the\s+)?`?note`?
    |\bgoes\s+in\s+the\s+note
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
    return bool(BARE_NOTE.search(line) and BARE_SINK_VERB.search(line))


def allowed(line: str) -> bool:
    if (
        SCORE_OR_WAKE.search(line)
        and not BACKTICK_OR_MILL.search(line)
        and not SINK_INTO_NOTE.search(line)
    ):
        return True
    if is_field_or_english(line):
        return True
    # Leftover text sent to mill note is never allowed, even on a --done-when line.
    if SINK_INTO_NOTE.search(line) and not REDIRECT.search(line):
        return False
    lowered = line.lower()
    if "in its own mill note" in lowered or "in its own note" in lowered:
        return False
    if REDIRECT.search(line):
        return True
    if ALLOWED_TIE.search(line) and not SINK_INTO_NOTE.search(line):
        return True
    if is_command_list(line):
        return True
    return False


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
    out: list[tuple[int, str]] = []

    def add(node: ast.AST, value: object) -> None:
        if isinstance(value, str) and HINTISH.search(value):
            out.append((getattr(node, "lineno", 0), value.replace("\n", " ")))

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            name = ""
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in {"CoordError", "add_argument", "ArgumentParser", "add_parser"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant):
                        add(arg, arg.value)
                for kw in node.keywords:
                    if kw.arg in {"help", "description", "epilog"} and isinstance(
                        kw.value, ast.Constant
                    ):
                        add(kw.value, kw.value.value)
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> None:
            if isinstance(node.value, ast.Constant):
                add(node.value, node.value.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if isinstance(node.value, ast.Constant):
                add(node.value, node.value.value)
            self.generic_visit(node)

    Visitor().visit(tree)
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
