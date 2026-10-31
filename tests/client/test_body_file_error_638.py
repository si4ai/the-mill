"""#638: a positional body or a missing --body-file names the fix in one line (F81)."""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser

FIX = "write the body to a UTF-8 file and pass --body-file PATH"


@pytest.mark.parametrize(
    "argv",
    [
        ["reply", "1", "x"],
        ["reply", "1"],
        ["send", "desk", "X", "x"],
        ["send", "desk", "X"],
    ],
)
def test_missing_body_file_names_the_fix(argv, capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        _build_parser().parse_args(argv)
    assert ei.value.code == 2
    err = capsys.readouterr().err
    last = err.strip().splitlines()[-1]
    assert FIX in last
    assert "<body>" not in err


def test_reply_extra_positional_names_the_fix(tmp_path, capsys) -> None:
    body = tmp_path / "b.txt"
    body.write_text("hi", encoding="utf-8")
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["reply", "1", "x", "--body-file", str(body)])
    err = capsys.readouterr().err
    assert "unrecognized arguments: x" in err
    assert FIX in err
    assert "see: mill help reply" in err
