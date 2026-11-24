"""Token-efficiency metrics for the rco report job (card 1228).

One file per pull request, rco-metrics.json, uploaded with the reports as
an artifact so a desk can read it without a browser. It compares what an
agent would read without rco (every changed file at the head, plus the
in-repo files those import, one hop) with what it reads with rco (the
`rco pack --for CHANGED` markdown). Both sides are counted in bytes and
in tokens of one tokenizer.

    python tools/rco_metrics.py measure --base SHA --head SHA --pr N \
        --pack pack.md --out rco-metrics.json
    python tools/rco_metrics.py check rco-metrics.json

`measure` runs in the rco job, where the rco lock (tools/ci-lock/rco.txt)
is installed: the import hop uses rco's own resolver, so both sides see
the same graph. `check` exits 1 when the file is missing or a field is
absent, so the job fails instead of uploading nothing. `pack_overrun` is
recorded when the pack footer is over budget; it is not required by
`check` and does not fail the job. Standard library only for `check`
and for the counting itself.
"""
from __future__ import annotations

import argparse
import re
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

SCHEMA = 1
TOKENIZER = "tiktoken o200k_base"
FIELDS = ("schema", "pr", "base_sha", "head_sha", "rco_version", "tokenizer",
          "changed_files", "without_rco", "with_rco", "ratio_tokens")
SIDE_FIELDS = ("files", "bytes", "tokens")
_PACK_USED = re.compile(r"^# budget used: ~(\d+) / (\d+) estimated tokens", re.M)


def pack_footer(text: str) -> tuple[int | None, int | None]:
    """used and budget from a pack markdown footer; (None, None) if absent."""
    m = _PACK_USED.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))



def estimate(text: str) -> int:
    """rco's own estimate (characters / 4), the fallback count."""
    return len(text) // 4


def counter() -> tuple[str, Callable[[str], int]]:
    """The tokenizer the metrics use, and its name; rco's estimate if absent."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
    except Exception as e:  # missing package or no encoding file
        print(f"rco_metrics: tiktoken unavailable ({type(e).__name__}); using chars/4",
              file=sys.stderr)
        return "estimate chars/4", estimate
    return TOKENIZER, lambda s: len(enc.encode(s, disallowed_special=()))


def read_set(changed: Iterable[str], graph: Mapping[str, Sequence[str]]) -> list[str]:
    """Changed files plus the in-repo files each imports (one hop), sorted."""
    out = set(changed)
    for p in list(out):
        out.update(graph.get(p, ()))
    return sorted(out)


def measure(changed: Sequence[str], graph: Mapping[str, Sequence[str]],
            blobs: Mapping[str, bytes], pack_text: str,
            count: Callable[[str], int]) -> dict:
    """Both sides of the comparison; files not in blobs (deleted) are skipped."""
    present = [p for p in changed if p in blobs]
    files = [p for p in read_set(present, graph) if p in blobs]
    text = "".join(blobs[p].decode("utf-8", "replace") for p in files)
    without = {"files": len(files), "bytes": sum(len(blobs[p]) for p in files),
               "tokens": count(text)}
    with_ = {"files": len(present), "bytes": len(pack_text.encode("utf-8")),
             "tokens": count(pack_text)}
    ratio = round(with_["tokens"] / without["tokens"], 4) if without["tokens"] else None
    return {"changed_files": len(present), "without_rco": without, "with_rco": with_,
            "ratio_tokens": ratio}


def _git(*args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], input=stdin,
                          capture_output=True, check=True).stdout


def _tree(sha: str) -> dict[str, str]:
    """path -> blob id of every regular file at sha."""
    out: dict[str, str] = {}
    for rec in _git("ls-tree", "-r", "-z", "--full-tree", sha).split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, typ, oid = meta.decode().split(" ")
        if typ == "blob" and mode in ("100644", "100755"):
            out[path.decode("utf-8", "surrogateescape")] = oid
    return out


def _blobs(tree: Mapping[str, str], paths: Iterable[str]) -> dict[str, bytes]:
    want = sorted({p for p in paths if p in tree})
    if not want:
        return {}
    out = _git("cat-file", "--batch", stdin=("\n".join(tree[p] for p in want) + "\n").encode())
    got, i = {}, 0
    for p in want:
        nl = out.index(b"\n", i)
        size = int(out[i:nl].split(b" ")[2])
        got[p] = out[nl + 1: nl + 1 + size]
        i = nl + 1 + size + 1
    return got


def changed_paths(base: str, head: str) -> list[str]:
    out = _git("diff", "--name-only", "-z", "--no-renames", base, head)
    return sorted(p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p)


def _measure_cmd(a: argparse.Namespace) -> int:
    from rco import __version__ as rco_version
    from rco.imports import file_graph

    tree = _tree(a.head)
    changed = changed_paths(a.base, a.head)
    py = [p for p in tree if p.endswith(".py")]
    graph = file_graph(sorted(tree), _blobs(tree, py))
    first = [p for p in changed if p in tree]
    blobs = _blobs(tree, read_set(first, graph))
    name, count = counter()
    pack_text = Path(a.pack).read_text(encoding="utf-8") if a.pack else ""
    used, footer_budget = pack_footer(pack_text)
    pack_budget = a.budget if footer_budget is None else footer_budget
    overrun = 0 if used is None else max(0, used - pack_budget)
    doc = {"schema": SCHEMA, "pr": a.pr, "base_sha": a.base, "head_sha": a.head,
           "rco_version": rco_version, "tokenizer": name, "pack_budget": pack_budget,
           "pack_overrun": overrun,
           **measure(changed, graph, blobs, pack_text, count)}
    if used is not None:
        doc["pack_used"] = used
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(doc, sort_keys=True))
    if overrun:
        print(f"rco_metrics: pack used ~{used} estimated tokens, over the budget of {pack_budget}",
              file=sys.stderr)
    return 0


def check(doc: object) -> list[str]:
    """Missing or wrong-typed fields; empty when the file is usable."""
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    bad = [f"missing {k}" for k in FIELDS if k not in doc]
    for side in ("without_rco", "with_rco"):
        s = doc.get(side)
        if isinstance(s, dict):
            bad += [f"{side}.{k} not an int" for k in SIDE_FIELDS
                    if not isinstance(s.get(k), int)]
        elif side in doc:
            bad.append(f"{side} not an object")
    if doc.get("schema") != SCHEMA and "schema" in doc:
        bad.append(f"schema {doc.get('schema')!r} != {SCHEMA}")
    return bad


def _check_cmd(a: argparse.Namespace) -> int:
    p = Path(a.file)
    if not p.is_file() or p.stat().st_size == 0:
        print(f"rco_metrics: {p} missing or empty", file=sys.stderr)
        return 1
    try:
        bad = check(json.loads(p.read_text(encoding="utf-8")))
    except ValueError as e:
        bad = [f"not JSON: {e}"]
    for b in bad:
        print(f"rco_metrics: {p}: {b}", file=sys.stderr)
    return 1 if bad else 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/rco_metrics.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="write rco-metrics.json for one pull request")
    m.add_argument("--base", required=True)
    m.add_argument("--head", required=True)
    m.add_argument("--pr", type=int, required=True)
    m.add_argument("--pack", help="the rco pack markdown for the changed files")
    m.add_argument("--budget", type=int, default=8000)
    m.add_argument("--out", required=True)
    c = sub.add_parser("check", help="exit 1 unless the metrics file is present and complete")
    c.add_argument("file")
    a = ap.parse_args(argv)
    return _measure_cmd(a) if a.cmd == "measure" else _check_cmd(a)


if __name__ == "__main__":
    raise SystemExit(main())
