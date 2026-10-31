"""#794: a records test that takes the MySQL `cn` fixture carries the sql mark.

CI's pytest_no_sql job has no MySQL, so an unmarked `cn` test skips there on
"Can't connect to MySQL server", and pytest_sql deselects it with -m sql. It
never runs in CI. This check reads the test files (no MySQL needed) and fails
when a test function takes `cn` without a module, class or function sql mark.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "tests" / "server" / "records"


def _sql(node: ast.AST) -> bool:
    return "mark.sql" in ast.unparse(node)


def _unmarked(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and _sql(node.value) and any(
            getattr(t, "id", "") == "pytestmark" for t in node.targets
        ):
            return []
    out: list[str] = []

    def walk(body: list[ast.stmt], marked: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, marked or any(_sql(d) for d in node.decorator_list))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test") or marked:
                    continue
                if any(_sql(d) for d in node.decorator_list):
                    continue
                if "cn" in [a.arg for a in node.args.args]:
                    out.append("%s::%s" % (path.relative_to(ROOT).as_posix(), node.name))

    walk(tree.body, False)
    return out


def test_every_cn_test_is_marked_sql() -> None:
    bad = [n for p in sorted(RECORDS.rglob("test_*.py")) for n in _unmarked(p)]
    assert bad == [], "takes the MySQL cn fixture without the sql mark: %s" % bad
