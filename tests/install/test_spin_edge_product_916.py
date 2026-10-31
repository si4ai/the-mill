"""Card 916: every required SPIN product edge names a deterministic test."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_check_spin_edges_maps_every_required_id(capsys) -> None:
    """F209: on-demand sync finds a SPIN <id> token for each product_edges.txt id."""
    script = ROOT / "tools" / "check_spin_edges.py"
    # run as __main__
    old = sys.argv[:]
    try:
        sys.argv = [str(script)]
        try:
            runpy.run_path(str(script), run_name="__main__")
            code = 0
        except SystemExit as e:
            code = int(e.code or 0)
    finally:
        sys.argv = old
    out = capsys.readouterr().out
    assert code == 0, out
    assert "unmapped" not in out, out
    assert "mapped  L01" in out and "mapped  W23" in out and "mapped  JOIN_RETIRED" in out


def test_product_edges_list_covers_card_916_ids() -> None:
    text = (ROOT / "verify" / "spin" / "product_edges.txt").read_text(encoding="utf-8")
    need = {
        "L01", "L02", "L05", "L06", "W07", "W23", "H11",
        "D4", "D5", "D6", "N1", "N2", "N4", "JOIN_RETIRED",
    }
    got = {ln.split("#", 1)[0].strip() for ln in text.splitlines() if ln.split("#", 1)[0].strip()}
    assert need <= got, need - got
