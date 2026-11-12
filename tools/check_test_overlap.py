#!/usr/bin/env python3
"""Inventory tests and checks; group likely overlaps; list uncovered F-rows.

Sources: pytest tests under tests/ (AST collect, or pytest --collect-only),
CI workflow jobs and steps, verify/spin checks, tools/check_* and
verify/*/run.sh plus check_anchors.py. Each item is mapped to an owner
(from path) and to the F-row or behaviour it asserts (docstrings, names,
regression-matrix links, F-refs).

Overlap is a fact to review, not a block: orthogonal checks are fine;
duplicate ones cost CI time. By default the command exits 0 after
printing the report, even when it finds something: it is a fact
report, not a CI gate on main. --strict exits 1 when a duplicate
cluster or uncovered F-row is present (for tests and a deliberate
check).

Deterministic: the same commit produces the same report, sorted, with
no timestamps in the result. Standard library only (PyYAML used if
present for workflows; a line parser is the fallback).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

F_ID_RE = re.compile(
    r"\b((?:S-\d+|F\d+[A-Za-z0-9]*|F-[a-z0-9]+(?:-[a-z0-9]+)*))\b"
)
SPIN_ROW_RE = re.compile(
    r"^([A-Z][A-Z0-9]{1,4})\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$"
)
PATH_PREFIXES = (
    "tests/",
    "tools/",
    "verify/",
    "docs/",
    ".github/",
    "ci/",
    "scripts/",
    "agent_coord/",
    "build_backend/",
)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def repo_commit(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def owner_for(rel: str) -> str:
    p = rel.replace("\\", "/")
    if p.startswith("tests/validator/") or "check_validator_pass" in p or p.endswith(
        "validator.yml"
    ):
        return "validator"
    if p.startswith("tests/wall/"):
        return "wall-ui"
    if "cold_measure" in p or p.startswith("tools/cold_measure"):
        return "gardener"
    if "grok-tui" in p or "grok_tui" in p:
        return "grok-tui"
    if p.startswith("verify/spin/"):
        return "auditor"
    if p.startswith("verify/"):
        return "builder"
    if p.startswith(
        ("tests/", "tools/", ".github/", "ci/", "scripts/", "docs/")
    ):
        return "builder"
    return "unknown"


def load_catalog(root: Path) -> dict[str, dict[str, Any]]:
    """F/S rows from docs/security/regression/*.md (card 924 row files)."""
    catalog: dict[str, dict[str, Any]] = {}
    rows_dir = root / "docs" / "security" / "regression"
    if not rows_dir.is_dir():
        return catalog
    for path in sorted(rows_dir.glob("*.md")):
        stem = path.stem
        if not F_ID_RE.fullmatch(stem) and not re.match(
            r"^(?:S-\d+|F\d+[A-Za-z0-9]*|F-[a-z0-9]+(?:-[a-z0-9]+)*)$", stem
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        line = ""
        for raw in text.splitlines():
            if raw.startswith("|") and stem in raw.split("|")[1]:
                line = raw
                break
        tests: list[str] = []
        behaviour = ""
        if line:
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) >= 2:
                behaviour = re.sub(r"^`?%s`?(?:\s*\([^)]*\))?\s*" % re.escape(stem), "", cols[0]).strip()
                if len(cols) >= 2 and not behaviour:
                    behaviour = cols[1].strip()
            if len(cols) >= 4:
                tests_col = cols[3]
            elif len(cols) >= 2:
                tests_col = cols[-1]
            else:
                tests_col = ""
            for m in re.finditer(r"`([^`]+)`", tests_col):
                tests.append(m.group(1).strip())
            # also bare tests/ paths
            for m in re.finditer(r"(tests/[A-Za-z0-9_./:-]+)", tests_col):
                if m.group(1) not in tests:
                    tests.append(m.group(1))
        catalog[stem] = {
            "id": stem,
            "path": _rel(root, path),
            "behaviour": behaviour,
            "listed_tests": sorted(set(tests)),
        }
    return catalog


def extract_f_ids(text: str, catalog: Iterable[str]) -> list[str]:
    cat = set(catalog)
    found: list[str] = []
    for m in F_ID_RE.finditer(text or ""):
        i = m.group(1)
        if i in cat and i not in found:
            found.append(i)
    return found


def _doc(node: ast.AST) -> str:
    d = ast.get_docstring(node) or ""
    return d


def collect_pytest_ast(root: Path, catalog: Iterable[str]) -> list[dict[str, Any]]:
    tests_root = root / "tests"
    items: list[dict[str, Any]] = []
    if not tests_root.is_dir():
        return items
    for path in sorted(tests_root.rglob("*.py")):
        if path.name == "conftest.py":
            continue
        rel = _rel(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        file_doc = _doc(tree)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                nid = f"{rel}::{node.name}"
                blob = " ".join([file_doc, node.name, _doc(node)])
                items.append(_test_item(nid, rel, blob, catalog))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_doc = _doc(node)
                for m in node.body:
                    if isinstance(m, ast.FunctionDef) and m.name.startswith("test_"):
                        nid = f"{rel}::{node.name}::{m.name}"
                        blob = " ".join([file_doc, class_doc, node.name, m.name, _doc(m)])
                        items.append(_test_item(nid, rel, blob, catalog))
    items.sort(key=lambda x: x["id"])
    return items


def collect_pytest_collectonly(root: Path, catalog: Iterable[str]) -> list[dict[str, Any]] | None:
    """Optional: pytest --collect-only -q. Returns None if pytest cannot run."""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--override-ini=addopts=",
                "tests",
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode not in (0, 1, 2):
        return None
    items: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("=") or "error" in line.lower() and "collected" in line:
            continue
        # node id like tests/foo.py::test_bar
        if "::" in line and line.startswith("tests/"):
            rel = line.split("::", 1)[0]
            items.append(_test_item(line, rel, line, catalog))
    if not items:
        return None
    items.sort(key=lambda x: x["id"])
    return items


def _test_item(nid: str, rel: str, blob: str, catalog: Iterable[str]) -> dict[str, Any]:
    f_ids = extract_f_ids(blob, catalog)
    behaviour = f_ids[0] if f_ids else nid.split("::")[-1]
    return {
        "id": nid,
        "kind": "pytest",
        "path": rel,
        "owner": owner_for(rel),
        "f_rows": f_ids,
        "behaviour": behaviour,
    }


def _parse_workflow_text(text: str, rel: str, catalog: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
        except Exception:
            data = {}
        jobs = data.get("jobs") or {}
        if isinstance(jobs, dict):
            for job_name, job in sorted(jobs.items()):
                if not isinstance(job, dict):
                    continue
                jid = f"{rel}:job:{job_name}"
                jblob = " ".join(
                    [
                        job_name,
                        str(job.get("name") or ""),
                        json.dumps(job, sort_keys=True, default=str),
                    ]
                )
                f_ids = extract_f_ids(jblob, catalog)
                items.append(
                    {
                        "id": jid,
                        "kind": "ci_job",
                        "path": rel,
                        "owner": owner_for(rel),
                        "f_rows": f_ids,
                        "behaviour": f_ids[0] if f_ids else f"job {job_name}",
                    }
                )
                for i, step in enumerate(job.get("steps") or []):
                    if not isinstance(step, dict):
                        continue
                    name = str(step.get("name") or step.get("uses") or step.get("run") or i)
                    sid = f"{rel}:job:{job_name}:step:{_slug(name)}"
                    sblob = json.dumps(step, sort_keys=True, default=str)
                    sf = extract_f_ids(sblob + " " + name, catalog)
                    items.append(
                        {
                            "id": sid,
                            "kind": "ci_step",
                            "path": rel,
                            "owner": owner_for(rel),
                            "f_rows": sf,
                            "behaviour": sf[0] if sf else f"step {name}",
                        }
                    )
            return items
    # Fallback: job keys at indent 2 under jobs:
    in_jobs = False
    current_job = ""
    for line in text.splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs and re.match(r"^[A-Za-z]", line):
            in_jobs = False
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current_job = m.group(1)
            jid = f"{rel}:job:{current_job}"
            items.append(
                {
                    "id": jid,
                    "kind": "ci_job",
                    "path": rel,
                    "owner": owner_for(rel),
                    "f_rows": [],
                    "behaviour": f"job {current_job}",
                }
            )
            continue
        sm = re.match(r"^\s+- name:\s*(.+)$", line)
        if sm and current_job:
            name = sm.group(1).strip().strip("\"'")
            sid = f"{rel}:job:{current_job}:step:{_slug(name)}"
            items.append(
                {
                    "id": sid,
                    "kind": "ci_step",
                    "path": rel,
                    "owner": owner_for(rel),
                    "f_rows": extract_f_ids(name, catalog),
                    "behaviour": f"step {name}",
                }
            )
    return items


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip())[:80].strip("-")
    return s or "unnamed"


def collect_workflows(root: Path, catalog: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return items
    for path in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        rel = _rel(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        items.extend(_parse_workflow_text(text, rel, catalog))
    items.sort(key=lambda x: x["id"])
    return items


def collect_spin(root: Path, catalog: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    run = root / "verify" / "spin" / "run.sh"
    if not run.is_file():
        return items
    rel = _rel(root, run)
    for line in run.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        m = SPIN_ROW_RE.match(line)
        if not m:
            continue
        cid, model, _defs, mode, expect, what = m.groups()
        blob = " ".join([cid, model, mode, expect, what])
        f_ids = extract_f_ids(blob, catalog)
        items.append(
            {
                "id": f"verify/spin:{cid}",
                "kind": "spin",
                "path": rel,
                "owner": owner_for(rel),
                "f_rows": f_ids,
                "behaviour": f_ids[0] if f_ids else f"{cid} {what.strip()}",
            }
        )
    items.sort(key=lambda x: x["id"])
    return items


def collect_scripts(root: Path, catalog: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    paths: list[Path] = []
    tools = root / "tools"
    if tools.is_dir():
        paths.extend(sorted(tools.glob("check_*")))
    verify = root / "verify"
    if verify.is_dir():
        for sub in sorted(verify.iterdir()):
            if not sub.is_dir():
                continue
            for name in ("run.sh", "check_anchors.py", "behave.py"):
                p = sub / name
                if p.is_file():
                    paths.append(p)
    seen: set[str] = set()
    for path in paths:
        rel = _rel(root, path)
        if rel in seen:
            continue
        seen.add(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            text = ""
        f_ids = extract_f_ids(rel + " " + text, catalog)
        items.append(
            {
                "id": rel,
                "kind": "script",
                "path": rel,
                "owner": owner_for(rel),
                "f_rows": f_ids,
                "behaviour": f_ids[0] if f_ids else path.name,
            }
        )
    items.sort(key=lambda x: x["id"])
    return items


def apply_catalog_links(
    items: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]
) -> None:
    """Attach F-rows to pytest items named in a regression row's test list."""
    for fid, row in catalog.items():
        for listed in row.get("listed_tests") or []:
            listed = listed.strip().strip("`")
            if not listed:
                continue
            # exact or prefix match on pytest ids / paths
            for it in items:
                if it["kind"] not in {"pytest", "script", "spin", "ci_job"}:
                    continue
                nid = it["id"]
                path = it["path"]
                matched = (
                    nid == listed
                    or path == listed
                    or nid.startswith(listed)
                    or listed.startswith(nid)
                    or listed.startswith(path + "::")
                )
                if matched:
                    if fid not in it["f_rows"]:
                        it["f_rows"].append(fid)
                        it["f_rows"].sort()
                    if it["behaviour"] in {nid.split("::")[-1], Path(path).name}:
                        it["behaviour"] = fid
            # a listed path that matches no item is still recorded as uncovered


def cluster_duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group asserting items that share an F-row, or the same behaviour string.

    CI jobs/steps are inventoried but not clustered unless they name an F-row,
    so a generic pytest_sql job is not a duplicate of every test.
    """
    asserting = [
        it
        for it in items
        if it["kind"] in {"pytest", "spin", "script"}
        or (it["kind"] in {"ci_job", "ci_step"} and it["f_rows"])
    ]
    by_f: dict[str, list[str]] = defaultdict(list)
    by_beh: dict[str, list[str]] = defaultdict(list)
    for it in asserting:
        for fid in it["f_rows"]:
            by_f[fid].append(it["id"])
        if not it["f_rows"]:
            beh = (it.get("behaviour") or "").strip()
            if beh:
                by_beh[beh].append(it["id"])
    clusters: list[dict[str, Any]] = []
    for fid, ids in sorted(by_f.items()):
        uniq = sorted(set(ids))
        if len(uniq) >= 2:
            clusters.append(
                {"key": fid, "kind": "f_row", "items": uniq, "count": len(uniq)}
            )
    for beh, ids in sorted(by_beh.items()):
        uniq = sorted(set(ids))
        if len(uniq) >= 2:
            clusters.append(
                {"key": beh, "kind": "behaviour", "items": uniq, "count": len(uniq)}
            )
    clusters.sort(key=lambda c: (c["kind"], c["key"]))
    return clusters


def uncovered_f_rows(
    items: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    covered: set[str] = set()
    for it in items:
        covered.update(it.get("f_rows") or [])
    out: list[dict[str, Any]] = []
    for fid in sorted(catalog):
        if fid in covered:
            continue
        listed = catalog[fid].get("listed_tests") or []
        out.append(
            {
                "id": fid,
                "path": catalog[fid].get("path", ""),
                "behaviour": catalog[fid].get("behaviour", ""),
                "listed_tests": listed,
            }
        )
    return out


def missing_suites(root: Path) -> list[str]:
    notes: list[str] = []
    tests = root / "tests"
    if not (tests / "wall").is_dir():
        notes.append("wall-ui tests: no tests/wall directory in this repository")
    has_garden = False
    has_tui = False
    has_cold = False
    if tests.is_dir():
        for pth in tests.rglob("*"):
            name = pth.as_posix()
            if "garden" in name:
                has_garden = True
            if "grok-tui" in name or "grok_tui" in name:
                has_tui = True
            if "cold_measure" in name:
                has_cold = True
    tools = root / "tools"
    if tools.is_dir():
        for pth in tools.glob("*cold_measure*"):
            has_cold = True
            break
    if not has_garden and not has_cold:
        notes.append("gardener tests: not a test tree in this repository")
    elif not has_garden and has_cold:
        notes.append("gardener tests: no test tree; cold-measure tools in this repository are mapped to gardener")
    if not has_tui:
        notes.append("grok-tui tests: not a test tree in this repository")
    return notes


def build_report(
    root: Path,
    *,
    use_pytest: bool,
) -> dict[str, Any]:
    catalog = load_catalog(root)
    cat_ids = list(catalog)
    pytest_items: list[dict[str, Any]] | None = None
    collect_method = "ast"
    if use_pytest:
        pytest_items = collect_pytest_collectonly(root, cat_ids)
        if pytest_items is not None:
            collect_method = "pytest-collect-only"
    if pytest_items is None:
        pytest_items = collect_pytest_ast(root, cat_ids)
    items: list[dict[str, Any]] = []
    items.extend(pytest_items)
    items.extend(collect_workflows(root, cat_ids))
    items.extend(collect_spin(root, cat_ids))
    items.extend(collect_scripts(root, cat_ids))
    apply_catalog_links(items, catalog)
    for it in items:
        it["f_rows"] = sorted(set(it.get("f_rows") or []))
    items.sort(key=lambda x: (x["kind"], x["id"]))
    dups = cluster_duplicates(items)
    uncovered = uncovered_f_rows(items, catalog)
    owners = sorted({it["owner"] for it in items})
    commit = repo_commit(root)
    counts = {
        "commit": commit,
        "items": len(items),
        "pytest": sum(1 for it in items if it["kind"] == "pytest"),
        "ci_jobs": sum(1 for it in items if it["kind"] == "ci_job"),
        "ci_steps": sum(1 for it in items if it["kind"] == "ci_step"),
        "spin_checks": sum(1 for it in items if it["kind"] == "spin"),
        "scripts": sum(1 for it in items if it["kind"] == "script"),
        "owners": len(owners),
        "owner_names": owners,
        "f_rows_catalog": len(catalog),
        "duplicate_clusters": len(dups),
        "uncovered_f_rows": len(uncovered),
    }
    return {
        "commit": commit,
        "collect": collect_method,
        "counts": counts,
        "missing_suites": missing_suites(root),
        "items": items,
        "duplicates": dups,
        "uncovered_f_rows": uncovered,
    }


def render_md(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Test overlap report",
        "",
        f"Commit: `{report.get('commit') or 'none'}`",
        f"Collect: `{report.get('collect')}`",
        "",
        "## Counts",
        "",
        f"- Inventory items: **{c['items']}**",
        f"- Pytest tests: **{c['pytest']}**",
        f"- CI jobs: **{c['ci_jobs']}**, steps: **{c['ci_steps']}**",
        f"- SPIN checks: **{c['spin_checks']}**",
        f"- Scripts: **{c['scripts']}**",
        f"- Owners: **{c['owners']}** ({', '.join(c['owner_names'])})",
        f"- F/S rows in catalog: **{c['f_rows_catalog']}**",
        f"- Duplicate clusters: **{c['duplicate_clusters']}**",
        f"- Uncovered F/S rows: **{c['uncovered_f_rows']}**",
        "",
    ]
    if report.get("missing_suites"):
        lines += ["## Suites not in this repository", ""]
        for n in report["missing_suites"]:
            lines.append(f"- {n}")
        lines.append("")
    lines += ["## Duplicate clusters", ""]
    dups = report.get("duplicates") or []
    if not dups:
        lines += ["None.", ""]
    else:
        for cl in dups:
            lines.append(f"- `{cl['key']}` ({cl['kind']}, {cl['count']} items)")
            for i in cl["items"]:
                lines.append(f"  - `{i}`")
        lines.append("")
    lines += ["## Uncovered F/S rows", ""]
    unc = report.get("uncovered_f_rows") or []
    if not unc:
        lines += ["None.", ""]
    else:
        for row in unc:
            lines.append(f"- `{row['id']}`  -  {row.get('behaviour') or ''}".rstrip())
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", required=True, help="Repository root to inventory")
    p.add_argument("--out-json", default="", help="Write JSON report here")
    p.add_argument("--out-md", default="", help="Write markdown report here")
    p.add_argument(
        "--pytest-collect",
        action="store_true",
        help="Prefer pytest --collect-only (falls back to AST)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when a duplicate cluster or uncovered F-row is present",
    )
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    report = build_report(root, use_pytest=args.pytest_collect)
    text_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    text_md = render_md(report)
    if args.out_json:
        Path(args.out_json).write_text(text_json, encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(text_md, encoding="utf-8")
    c = report["counts"]
    print(
        "commit={commit} pytest={pytest} items={items} owners={owners} "
        "clusters={duplicate_clusters} uncovered={uncovered_f_rows} "
        "spin={spin_checks} scripts={scripts} ci_jobs={ci_jobs}".format(**c)
    )
    if args.strict and (c["duplicate_clusters"] or c["uncovered_f_rows"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
