"""A name outside SQL is one object.

name.type is the kind: project, desk, role, label, res, tree, or other.
name.str is the bare name.

The name table stores type and a bare string. id is the primary key.
idx_name is the unique key (name). idx_type_name (type, name) is a plain key
for reading one type's names (card 1234).
"""

from __future__ import annotations


class MillName:
    """The pair a caller holds. SQL owns the stored spelling."""

    __slots__ = ("_type", "_bare")

    def __init__(self, type: str, bare: str):
        self._type = (type or "other").strip().lower() or "other"
        self._bare = "" if bare is None else str(bare)

    @property
    def type(self) -> str:
        """Kind word."""
        return self._type

    @property
    def str(self) -> str:
        """Bare name."""
        return self._bare

    def json(self) -> dict[str, str]:
        """Wire object. JavaScript reads .type and .name."""
        return {"type": self.type, "name": self.str}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MillName):
            return NotImplemented
        return self.type == other.type and self.str == other.str

    def __hash__(self) -> int:
        return hash((self.type, self.str))

    def __repr__(self) -> str:
        return f"MillName(type={self.type!r}, str={self.str!r})"
