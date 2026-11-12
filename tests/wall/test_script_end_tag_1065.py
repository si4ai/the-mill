"""card 1065: a script end tag may have space before the closing bracket."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import agent_coord

CHECK = (
    Path(agent_coord.__file__).resolve().parent
    / "web"
    / "wall_ui"
    / "lib"
    / "check.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("wall_check_1065", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_end_tag_space_is_read() -> None:
    extract = _load().extract_board_inline_js
    assert "danger()" in extract("<script>danger()</script >")
    assert "danger()" in extract("<script>danger()</SCRIPT\t>")
    assert "danger()" in extract("<script>danger()</script>")
    external = extract("<script>src=app.js</script>")
    assert external == ""
    assert "danger()" not in extract("<script>danger()")
