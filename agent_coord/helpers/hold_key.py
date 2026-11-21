"""Card 1267: the one-use release key of a hold.

The client makes the key and sends only its sha256 (kh) with the take. The server
stores kh on the take transition (meta.kh) and hashes a presented key to compare.
The plain key is printed once, to the caller, and is never stored or logged.
"""
from __future__ import annotations

import hashlib
import re
import secrets

_KH = re.compile(r"^[0-9a-f]{64}$")


def key_hash(key: str) -> str:
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()


def new_key() -> tuple[str, str]:
    """(release_key, kh): a fresh key and the hash the take sends.

    The "hk_" prefix keeps a key that token_urlsafe starts with "-" from being read
    as a flag by mill drop NAME --key KEY.
    """
    key = "hk_" + secrets.token_urlsafe(32)
    return key, key_hash(key)


def is_kh(value: object) -> bool:
    return isinstance(value, str) and bool(_KH.match(value))
