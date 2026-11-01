# -*- coding: utf-8 -*-
"""Card 342: concurrent _replace must not race on a shared .tmp name."""
from __future__ import annotations

import threading
from pathlib import Path

from agent_coord.client import offices


def test_replace_parallel_writers_all_succeed(tmp_path: Path) -> None:
    target = tmp_path / "active"
    errors: list[BaseException] = []
    n = 32

    def write(i: int) -> None:
        try:
            offices._replace(target, f"office-{i}\n")
        except BaseException as exc:  # noqa: BLE001 - collect any race failure
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], errors
    assert target.is_file()
    body = target.read_text(encoding="utf-8").strip()
    assert body.startswith("office-")
    # no leftover shared active.tmp
    assert not (tmp_path / "active.tmp").exists()


def test_write_global_active_parallel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(offices, "_home", lambda dest=None: tmp_path)
    (tmp_path / "alias").mkdir()
    for name in ("alpha", "beta", "gamma"):
        (tmp_path / "alias" / name).write_text("office.example\n", encoding="utf-8")
    errors: list[BaseException] = []
    names = ["alpha", "beta", "gamma"] * 10

    def one(name: str) -> None:
        try:
            offices.write_global_active(name, dest=tmp_path)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], errors
    assert (tmp_path / "active").read_text(encoding="utf-8").strip() in {"alpha", "beta", "gamma"}
