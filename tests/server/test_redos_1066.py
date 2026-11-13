"""card 1066: the pan, ttl, and home-path patterns match in linear time."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

from agent_coord.server.admin import door
from agent_coord.server.redact import _PAN, PH, redact_text

ROOT = Path(__file__).resolve().parents[2]
_SLOW_S = 0.3


def _pack():
    spec = importlib.util.spec_from_file_location("check_pack_1066", ROOT / "tools" / "check_pack.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _under(label: str, run) -> None:
    started = time.perf_counter()
    run()
    elapsed = time.perf_counter() - started
    assert elapsed < _SLOW_S, "%s took %.3fs" % (label, elapsed)


def test_pan_and_home_patterns_compile_on_py310() -> None:
    assert "?+" not in _PAN.pattern and "++" not in _PAN.pattern
    pat = _pack()._HOME_PATH_RE.pattern
    assert "?+" not in pat and "++" not in pat and "}+" not in pat


def test_pan_card_and_spaced_card_match_short_does_not() -> None:
    card = "4111" + "1111" + "1111" + "1111"
    spaced = "4111 1111 1111 1111"
    assert _PAN.search("card " + card)
    assert _PAN.search("card " + spaced)
    assert _PAN.search("4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1")
    assert _PAN.search("123456789012") is None
    assert _PAN.search("12345") is None


@pytest.mark.parametrize("sep", [" ", "-", ""])
def test_pan_amex_4_6_5_is_redacted(sep: str) -> None:
    amex = sep.join(("3782", "822463", "10005"))
    out = redact_text("amex " + amex)[0]
    assert PH["pan"] in out and amex not in out


def _with_check(body: str) -> str:
    digits = [int(ch) for ch in body]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return body + str((10 - (total % 10)) % 10)


def _grouped(digits: str, widths: tuple[int, ...], sep: str) -> str:
    parts = []
    at = 0
    for width in widths:
        parts.append(digits[at:at + width])
        at += width
    return sep.join(parts)


@pytest.mark.parametrize("sep", [" ", "-"])
@pytest.mark.parametrize(
    ("widths", "length"),
    [((4, 6, 4), 14), ((4, 4, 5), 13), ((4, 4, 4, 4, 3), 19)],
)
def test_pan_other_groupings_are_redacted(sep: str, widths: tuple[int, ...], length: int) -> None:
    number = _grouped(_with_check("4" * (length - 1)), widths, sep)
    out = redact_text("card " + number)[0]
    assert PH["pan"] in out and number not in out


@pytest.mark.parametrize("sep", [" ", "-", ""])
def test_pan_visa_4_4_4_4_is_still_redacted(sep: str) -> None:
    visa = sep.join(("4111", "1111", "1111", "1111"))
    out = redact_text("card " + visa)[0]
    assert PH["pan"] in out and visa not in out


def test_parse_ttl_examples_and_junk() -> None:
    assert door.parse_ttl("3600")[0] == 3600
    assert door.parse_ttl("7d")[0] == 7 * 86400
    assert door.parse_ttl("24h")[0] == 24 * 3600
    assert door.parse_ttl("30m")[0] == 30 * 60
    assert door.parse_ttl("90s")[0] == 90
    assert door.parse_ttl("0") == (None, None)
    assert door.parse_ttl(0) == (None, None)
    assert door.parse_ttl("never") == (None, None)
    assert door.parse_ttl("") == (None, None)
    assert door.parse_ttl(None) == (None, None)
    with pytest.raises(ValueError):
        door.parse_ttl("junk")
    with pytest.raises(ValueError):
        door.parse_ttl("7x")


def test_home_path_ordinary_user_still_matches() -> None:
    mod = _pack()
    login = "".join(("fixture", "login"))
    windows = "".join(("C:", "\\", "Users", "\\", login, "\\", "mill"))
    linux = "".join(("/", "home", "/", login, "/.mill"))
    assert mod.text_has_personal_home_path(windows)
    assert mod.text_has_personal_home_path(linux)


def test_redos_patterns_finish_on_long_input() -> None:
    mod = _pack()
    _under("pan", lambda: _PAN.search("9" * 8000 + "x"))
    _under("pan spaced", lambda: _PAN.search("9 " * 8000 + "x"))
    _under("pan groups", lambda: _PAN.search("9999 " * 4000 + "x"))
    _under("pan amex groups", lambda: _PAN.search("9999 999999 " * 2000 + "x"))
    _under("ttl", lambda: door._TTL_RE.search("1" + (" " * 8000) + "x"))
    _under("home backslash", lambda: mod._HOME_PATH_RE.search("\\" * 8000))
    _under("home slash", lambda: mod._HOME_PATH_RE.search("/" * 8000))
