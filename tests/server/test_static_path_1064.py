"""A lib name that passes the dot filter must not stat a file outside the root."""
from __future__ import annotations

from pathlib import Path

from agent_coord.server.middleware import _safe_static

# a real file in the repo, not under wall_ui/lib. its posix form is absolute
# on this host, so "lib/" plus that form joins off the static root.
_OUTSIDE = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_lib_posix_absolute_does_not_stat_outside(monkeypatch):
    outside = _OUTSIDE.resolve()
    assert outside.is_file()
    seen: list[Path] = []
    real_is_file = Path.is_file

    def _track(self: Path) -> bool:
        seen.append(Path(self))
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", _track)
    found = _safe_static("lib/" + outside.as_posix())
    assert found is None
    hit = [p for p in seen if p.resolve() == outside]
    assert hit == []
