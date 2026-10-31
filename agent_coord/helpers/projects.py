"""Up-front project check. Unknown, retired, and empty are a plain refusal."""
from __future__ import annotations


def project_refusal(command: str, project: str, names: list[str]) -> str | None:
    """None when project is a live name. Otherwise the refusal sentence.

    The sentence is `command: no such roster X; rosters: a, b. list them: mill member`.
    A blank project omits X. names are the live rosters, already ordered.
    """
    who = str(project or "").strip()
    live: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        nm = str(raw or "").strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        live.append(nm)
    if who and who in seen:
        return None
    shown = ", ".join(live) if live else "(none)"
    if who:
        return "%s: no such roster %s; rosters: %s. list them: mill member" % (command, who, shown)
    return "%s: no such roster; rosters: %s. list them: mill member" % (command, shown)
