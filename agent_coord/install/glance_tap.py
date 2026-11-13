# -*- coding: utf-8 -*-
"""Store a glance-tap digest. The tap values are not written.

mill install glance-tap
mill install glance-tap --generate

Prompts for the ordered tap values, then always prompts for a passphrase.
Enter at the passphrase prompt leaves it empty.
--generate picks the keys, prints the symbols once, then prompts.
Writes glance_tap = "<digest>" into the office config. The file gets the
digest only.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from agent_coord.server.glance import TAP_RE, digest_for, serial


def store(taps: list[str], passphrase: str = "", *, dest: str = "") -> dict:
    """Hash the ordered taps and save the digest. Raises ValueError on a bad tap."""
    lines = [str(t or "").strip() for t in taps]
    if not lines or any(TAP_RE.fullmatch(t) is None for t in lines):
        raise ValueError("tap required")
    if len(lines) > 16:
        raise ValueError("tap required")
    word = str(passphrase or "")
    digest = digest_for(lines, word)
    # serial() is the hashed text. Touch it so a bad passphrase shape fails here.
    serial(lines, word)
    from agent_coord.config import config_path, load_file, save_config

    path = Path(dest) / "config.toml" if dest else config_path()
    data = load_file(path)
    data["glance_tap"] = digest
    written = save_config(data, path)
    return {"ok": True, "stored": True, "path": str(written)}


def key_name(index: int) -> str:
    """10-letter name the keypad posts for this symbol. Same formula as the glass."""
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    n = (int(index) + 1) * 7919
    chars: list[str] = []
    for step in range(10):
        n = ((n * 1103515245) + 12345 + step * 97) & 0xFFFFFFFF
        chars.append(alphabet[n % 26])
    return "".join(chars)


# emoji and description, keypad order. The 10-letter token is key_name(index) and is not shown.
MARKS: tuple[tuple[str, str], ...] = (
    ("🌞", "sun with a face"),
    ("🌙", "crescent moon"),
    ("⭐", "star"),
    ("⚡", "lightning"),
    ("🔥", "fire"),
    ("💧", "droplet"),
    ("❄", "snowflake"),
    ("🌈", "rainbow"),
    ("☁", "cloud"),
    ("☀", "sun"),
    ("🌸", "cherry blossom"),
    ("🌲", "evergreen"),
    ("🍀", "four-leaf clover"),
    ("🍁", "maple leaf"),
    ("🍄", "mushroom"),
    ("🌵", "cactus"),
    ("🌻", "sunflower"),
    ("🌴", "palm"),
    ("🌹", "rose"),
    ("🌺", "hibiscus"),
    ("🐶", "dog"),
    ("🐱", "cat"),
    ("🐭", "mouse"),
    ("🐰", "rabbit"),
    ("🦊", "fox"),
    ("🐻", "bear"),
    ("🐼", "panda"),
    ("🐨", "koala"),
    ("🐯", "tiger"),
    ("🦁", "lion"),
    ("🐮", "cow"),
    ("🐷", "pig"),
    ("🐸", "frog"),
    ("🐵", "monkey"),
    ("🐔", "chicken"),
    ("🐧", "penguin"),
    ("🐦", "bird"),
    ("🦄", "unicorn"),
    ("🐝", "bee"),
    ("🦋", "butterfly"),
    ("🍎", "apple"),
    ("🍊", "orange"),
    ("🍋", "lemon"),
    ("🍌", "banana"),
    ("🍉", "watermelon"),
    ("🍇", "grapes"),
    ("🍓", "strawberry"),
    ("🍍", "pineapple"),
    ("🍑", "peach"),
    ("🥝", "kiwi"),
    ("🥑", "avocado"),
    ("🌽", "corn"),
    ("🥕", "carrot"),
    ("🍞", "bread"),
    ("🧀", "cheese"),
    ("🍕", "pizza"),
    ("🍔", "burger"),
    ("🍪", "cookie"),
    ("🍩", "donut"),
    ("🎂", "cake"),
    ("🚗", "car"),
    ("🛵", "scooter"),
    ("🚌", "bus"),
    ("🚓", "police car"),
    ("🚑", "ambulance"),
    ("🚒", "fire engine"),
    ("🚜", "tractor"),
    ("🚲", "bicycle"),
    ("✈", "airplane"),
    ("🚀", "rocket"),
    ("⛵", "sailboat"),
    ("⚓", "anchor"),
    ("🏠", "house"),
    ("⛺", "tent"),
    ("🏰", "castle"),
    ("🗽", "statue"),
    ("🗿", "moai"),
    ("⛪", "church"),
    ("⛲", "fountain"),
    ("🌋", "volcano"),
    ("⌚", "watch"),
    ("⏰", "alarm clock"),
    ("🔑", "key"),
    ("🔒", "lock"),
    ("✉", "envelope"),
    ("✂", "scissors"),
    ("✏", "pencil"),
    ("📌", "pushpin"),
    ("📎", "paperclip"),
    ("🔍", "magnifying glass"),
    ("♔", "chess king"),
    ("🎸", "guitar"),
    ("🎺", "trumpet"),
    ("🎲", "die"),
    ("🎯", "target"),
    ("♠", "spade"),
    ("♥", "heart"),
    ("♦", "diamond"),
    ("♣", "club"),
    ("🎵", "musical note"),
)


def generate_keys(count: int = 4) -> list[dict[str, str]]:
    """Pick distinct keypad symbols. The caller shows them once and stores the digest."""
    n = int(count)
    if n < 1 or n > 16:
        raise ValueError("tap required")
    picked = secrets.SystemRandom().sample(range(len(MARKS)), n)
    keys: list[dict[str, str]] = []
    for index in picked:
        symbol, description = MARKS[index]
        keys.append({
            "symbol": symbol,
            "description": description,
            "name": key_name(index),
        })
    return keys


def _digit_count(generate: int | str) -> int:
    """Blank entry keeps 4. A number on the command line skips the question."""
    if generate != "ask":
        return int(generate)
    if not sys.stdin.isatty():
        return 4
    sys.stderr.write("Number of digits [4]: ")
    raw = input().strip()
    if not raw:
        return 4
    return int(raw)


def _show_keys(keys: list[dict[str, str]]) -> None:
    sys.stderr.write(
        "Glance tap, in order. Write this down. The office file stores the digest only.\n"
    )
    for n, key in enumerate(keys, 1):
        sys.stderr.write(f"{n}. {key['symbol']}  {key['description']}\n")


def _read_passphrase() -> str:
    """Always ask. Enter leaves the passphrase empty."""
    import getpass

    return getpass.getpass("Passphrase (Enter leaves it empty): ")


def configure_cli(
    *,
    taps: list[str],
    dest: str = "",
    generate: int | str | None = None,
) -> dict:
    """Admin entry. A tty can type the taps. The command result has no sequence."""
    try:
        lines = [str(t or "").strip() for t in taps if str(t or "").strip()]
        if generate is not None:
            if lines:
                return {"ok": False, "error": "tap required"}
            keys = generate_keys(_digit_count(generate))
            lines = [key["name"] for key in keys]
            _show_keys(keys)
        elif not lines:
            if not sys.stdin.isatty():
                return {"ok": False, "error": "tap required"}
            sys.stderr.write("Tap values, one per line, in order. Blank line ends.\n")
            while True:
                line = input().strip()
                if not line:
                    break
                lines.append(line)
        return store(lines, _read_passphrase(), dest=dest)
    except ValueError:
        return {"ok": False, "error": "tap required"}
