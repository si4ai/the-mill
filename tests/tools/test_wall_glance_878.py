"""Card 878: tools/glance.py imports without a browser and keeps its report text diffable."""
from __future__ import annotations

import pytest

from tools import glance


def test_norm_masks_clocks_dates_and_durations():
    text = "seen 12:04:33, 2026-01-02, took 340 ms, 5 min ago, 3.5 s"
    assert glance.norm(text) == "seen #, #, took #, #, #"


def test_norm_keeps_plain_counts():
    assert glance.norm("12 open, 3 done") == "12 open, 3 done"


def test_cli_needs_url_and_tag(capsys):
    with pytest.raises(SystemExit) as e:
        glance.main([])
    assert e.value.code == 2
    assert "url" in capsys.readouterr().err
