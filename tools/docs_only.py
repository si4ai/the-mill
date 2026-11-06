"""Emit a fail-closed pytest skip decision without installing the pack."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def skip_pytest(event_name: str, event: dict) -> bool:
    """Compare the whole PR or queued squash; other events run pytest."""
    try:
        if event_name == "pull_request":
            base = event["pull_request"]["base"]["sha"]
            head = event["pull_request"]["head"]["sha"]
            separator = "..."
        elif event_name == "merge_group":
            base = event["merge_group"]["base_sha"]
            head = event["merge_group"]["head_sha"]
            separator = ".."
        else:
            return False
        if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
            return False
        # Disabling rename detection lists both sides as delete/add. NULs keep
        # tabs, newlines and undecodable filename bytes from changing the rule.
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}{separator}{head}", "--"],
            check=True, capture_output=True, timeout=60,
        )
        paths = result.stdout.split(b"\0")
        if not paths[-1] == b"":
            return False
        paths.pop()
        return bool(paths) and all(
            not path.startswith(b"tests/") and (path == b"LICENSE" or path.endswith(b".md"))
            for path in paths
        )
    except (KeyError, TypeError, OSError, ValueError, subprocess.SubprocessError):
        return False


def main() -> None:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        skip = skip_pytest(os.environ.get("GITHUB_EVENT_NAME", ""), event)
    except (KeyError, OSError, ValueError):
        skip = False
    print(f"skip_pytest={str(skip).lower()}")


if __name__ == "__main__":
    main()
