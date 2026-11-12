"""Shipped docs must not map mill note to card text (card 1125 / D5).

note sets progress, --eta, --started, or --done-when. Free text goes through
replace-body. A hand sweep of leftover diary wording missed this class three
times (D3, D4, D5); this check scans every doc in pyproject data-files.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]

SCORE_OR_WAKE = re.compile(
    r"\b(?:score|wake-done)\b.{0,160}--note|--note.{0,160}\b(?:score|wake-done)\b",
    re.IGNORECASE | re.DOTALL,
)
# Role words that mean "put free text here" when tied to mill note.
SINK = re.compile(
    r"(?i)("
    r"`note`\s+gap"
    r"|mill note on\b"
    r"|goes in the note"
    r"|note its mail id"
    r"|put the rest in a `note`"
    r"|into `note`"
    r"|in a `note`"
    r"|in the note"
    r"|pointer in (?:detail/)?`note`"
    r"|`detail`/`note`"
    r"|`detail`\s*/\s*`note`"
    r"|detail\s*/\s*`note`"
    r"|brief section / `note`"
    r"|`note`\s+forge"
    r"|`note`\s+outcome"
    r"|`note`\s+reason"
    r"|`note`\s+payment"
    r"|`note`\s+\(ledger"
    r"|`send`/`note`"
    r"|`note` and/or"
    r"|`note` crumbs"
    r"|Interview notes are `note`"
    r"|`note`\s+pointer"
    r"|`note` \(note !="
    r"|`note` \(\+\s*`send`"
    r"|\(\+\s*`note` on card"
    r"|`note` decision"
    r"|`note` to amend"
    r"|`note` \(path"
    r"|path in note"
    r"|`note` \(asker"
    r"|`note` by asker"
    r"|`note` on opp"
    r"|`note` why"
    r"|`note` canonical"
    r"|`note` on card"
    r"|note \+ done when"
    r"|note \+ optional"
    r"|mail thread / note"
    r"|workaround \| note on card"
    r"|`note` \(\+\s*`send` HM"
    r")"
)
PROGRESS_LEFT = re.compile(
    r"^(?:next step\s*/\s*)?progress$",
    re.IGNORECASE,
)
BARE_NOTE_CELL = re.compile(
    r"^\s*\|\s*(?P<left>[^|]+)\s*\|\s*(?P<right>`note`|note)\s*\|"
)


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


def _bare_note_non_progress(line: str) -> bool:
    m = BARE_NOTE_CELL.search(line)
    if not m:
        return False
    return not PROGRESS_LEFT.match(m.group("left").strip())


def bad_lines(text: str) -> list[str]:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if SCORE_OR_WAKE.search(line) and not re.search(
            r"mill note|`note` gap|put the rest in a `note`|goes in the note|note its mail id",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(r"note on the card.*replace-body", line, re.IGNORECASE):
            continue
        if SINK.search(line) or _bare_note_non_progress(line):
            hits.append("%s: %s" % (i, line.strip()))
    return hits


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


def test_scanner_flags_a_diary_mapping_and_allows_progress():
    assert bad_lines("put long text in a room letter and note its mail id.")
    assert bad_lines("| synthesize / revise | `note` |")
    assert bad_lines("| findings | brief section / `note` |")
    assert not bad_lines("| progress | `note` |")
    assert not bad_lines("| next step / progress | `note` |")
    assert not bad_lines(
        "A progress token as text (`9/12`) sets `progress`. `--eta` sets eta. "
        "Card text changes with `mill replace-body todo ID TEXT`. `--note` does not append."
    )
