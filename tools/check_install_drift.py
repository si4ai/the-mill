#!/usr/bin/env python3
"""Install drift: per-object sha256 of routines, tables, and columns.

For a given MySQL connection, dump routine bodies (information_schema.ROUTINES)
plus table and column schema, normalize them (strip DEFINER, whitespace,
AUTO_INCREMENT counters), and print a sha256 per object. Diff those against
the same normalization of the repo SQL, loaded into a throwaway database
on a local mysqld via agent_coord.install.migrate.ensure.

The live compare is a SQL test (pytest.mark.sql). SQL tests skip when
no throwaway mysqld is available; CI pytest_sql_run is the proof. The
demo starts its own throwaway mysqld (never a live office book).

By default the compare command exits 0 after printing the report, even
when it finds drift: it is a fact report, not a CI gate on main. Pass
--strict to exit 1 when drift is present (for tests and a deliberate
check). Exit 2 on a tool or connection error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import re

DEFINER_RE = re.compile(r"\s*DEFINER\s*=\s*(?:`[^`]+`|'[^']+'|\"[^\"]+\"|[^\s@]+)\s*@\s*(?:`[^`]+`|'[^']+'|\"[^\"]+\"|\S+)", re.I)
AUTO_INC_EQ_RE = re.compile(r"\s*AUTO_INCREMENT\s*=\s*\d+", re.I)
WS_RE = re.compile(r"\s+")


def normalize(text: Any) -> str:
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    s = "" if text is None else str(text)
    s = DEFINER_RE.sub(" ", s)
    s = AUTO_INC_EQ_RE.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def sha256(text: Any) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def connect(kwargs: dict[str, Any]):
    import mysql.connector

    kw = dict(kwargs)
    kw.setdefault("connection_timeout", 10)
    return mysql.connector.connect(**kw)


def dump_book(cn) -> dict[str, dict[str, str]]:
    """Map object id -> {kind, name, sha256, norm} for routines, tables, columns."""
    cur = cn.cursor()
    out: dict[str, dict[str, str]] = {}
    cur.execute(
        "SELECT ROUTINE_TYPE, ROUTINE_NAME, ROUTINE_DEFINITION, "
        "DTD_IDENTIFIER, IS_DETERMINISTIC, SQL_DATA_ACCESS, SECURITY_TYPE "
        "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() "
        "ORDER BY ROUTINE_TYPE, ROUTINE_NAME"
    )
    for typ, name, body, dtd, det, access, sec in cur.fetchall():
        key = f"routine {typ}.{name}"
        payload = " ".join(
            [
                typ or "",
                name or "",
                normalize(body),
                normalize(dtd),
                normalize(det),
                normalize(access),
                normalize(sec),
            ]
        )
        out[key] = {"kind": "routine", "name": f"{typ}.{name}", "sha256": sha256(payload), "norm": normalize(body)}
    cur.execute(
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
        "FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_NAME"
    )
    for name, engine, coll in cur.fetchall():
        key = f"table {name}"
        payload = " ".join([name or "", normalize(engine), normalize(coll)])
        out[key] = {"kind": "table", "name": name, "sha256": sha256(payload)}
    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, "
        "COLUMN_DEFAULT, EXTRA, COLLATION_NAME "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    )
    for table, col, typ, nullable, default, extra, coll in cur.fetchall():
        extra_n = AUTO_INC_EQ_RE.sub(" ", extra or "")
        # Keep the auto_increment flag; drop only a counter if one appears.
        key = f"column {table}.{col}"
        payload = " ".join(
            [
                table or "",
                col or "",
                normalize(typ),
                normalize(nullable),
                normalize(default),
                normalize(extra_n),
                normalize(coll),
            ]
        )
        out[key] = {"kind": "column", "name": f"{table}.{col}", "sha256": sha256(payload)}
    cur.close()
    return dict(sorted(out.items()))


def diff_dumps(gold: dict, subject: dict) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for key in sorted(set(gold) | set(subject)):
        if key not in subject:
            findings.append({"object": key, "kind": "missing_from_subject", "gold": gold[key]["sha256"], "subject": ""})
        elif key not in gold:
            findings.append({"object": key, "kind": "extra_in_subject", "gold": "", "subject": subject[key]["sha256"]})
        elif gold[key]["sha256"] != subject[key]["sha256"]:
            findings.append(
                {
                    "object": key,
                    "kind": "hash_mismatch",
                    "gold": gold[key]["sha256"],
                    "subject": subject[key]["sha256"],
                }
            )
    findings.sort(key=lambda f: (f["kind"], f["object"]))
    return findings


def ensure_book(cn, root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from agent_coord.install.migrate import ensure

    ensure(cn)
    try:
        cn.commit()
    except Exception:
        pass


def admin_and_db(kwargs: dict[str, Any], database: str):
    import mysql.connector

    admin_kw = dict(kwargs)
    admin_kw.pop("database", None)
    admin_kw["autocommit"] = True
    admin = mysql.connector.connect(**admin_kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{database}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    db_kw = dict(kwargs)
    db_kw["database"] = database
    db_kw["autocommit"] = False
    return mysql.connector.connect(**db_kw)


def default_mysqld_basedir() -> Path | None:
    env = os.environ.get("MILL_MYSQLD_BASEDIR") or ""
    if env and (Path(env) / "bin" / "mysqld").is_file():
        return Path(env)
    for cand in (Path("/tmp/mysql84"), Path("/usr/local/mysql")):
        if (cand / "bin" / "mysqld").is_file():
            return cand
    found = shutil.which("mysqld")
    if found:
        # .../bin/mysqld
        return Path(found).resolve().parent.parent
    return None


def pick_port(preferred: int = 3318) -> int:
    for port in range(preferred, preferred + 20):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
    raise RuntimeError("no free port in 3318-3337")


class LocalMysqld:
    """Throwaway mysqld with our datadir and port. Never reuse another instance."""

    def __init__(self, workdir: Path, basedir: Path, port: int | None = None):
        self.workdir = workdir
        self.basedir = basedir
        self.port = port or pick_port()
        self.datadir = workdir / "data"
        self.socket = workdir / "mysql.sock"
        self.pidfile = workdir / "mysqld.pid"
        self.errlog = workdir / "mysqld.log"
        self.proc: subprocess.Popen | None = None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        lib = str(self.basedir / "lib")
        env["LD_LIBRARY_PATH"] = lib + ((":" + env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else "")
        return env

    def initialize(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        if (self.datadir / "mysql").is_dir():
            return
        self.datadir.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self.basedir / "bin" / "mysqld"),
            "--initialize-insecure",
            f"--basedir={self.basedir}",
            f"--datadir={self.datadir}",
        ]
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if user:
            cmd.append(f"--user={user}")
        subprocess.run(cmd, env=self._env(), check=True, capture_output=True, text=True)

    def start(self) -> None:
        self.initialize()
        cmd = [
            str(self.basedir / "bin" / "mysqld"),
            f"--basedir={self.basedir}",
            f"--datadir={self.datadir}",
            f"--port={self.port}",
            f"--socket={self.socket}",
            f"--pid-file={self.pidfile}",
            f"--log-error={self.errlog}",
            "--bind-address=127.0.0.1",
            "--mysqlx=0",
        ]
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if user:
            cmd.append(f"--user={user}")
        self.proc = subprocess.Popen(
            cmd,
            env=self._env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        last = ""
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = self.errlog.read_text(encoding="utf-8", errors="replace")[-2000:] if self.errlog.is_file() else ""
                raise RuntimeError(f"mysqld exited {self.proc.returncode}: {tail}")
            try:
                cn = self.connect()
                cn.close()
                return
            except Exception as e:
                last = str(e)
                time.sleep(0.2)
        raise RuntimeError(f"mysqld did not accept connections: {last}")

    def connect(self, database: str | None = None):
        import mysql.connector

        kw: dict[str, Any] = {
            "user": "root",
            "password": "",
            "host": "127.0.0.1",
            "port": self.port,
            "unix_socket": str(self.socket),
            "connection_timeout": 5,
            "autocommit": True,
        }
        if database:
            kw["database"] = database
        return mysql.connector.connect(**kw)

    def connect_kwargs(self, database: str | None = None) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "user": "root",
            "password": "",
            "host": "127.0.0.1",
            "port": self.port,
            "unix_socket": str(self.socket),
        }
        if database:
            kw["database"] = database
        return kw

    def stop(self) -> None:
        pid = None
        if self.pidfile.is_file():
            try:
                pid = int(self.pidfile.read_text().strip())
            except ValueError:
                pid = None
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        elif pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self.proc = None


def render_md(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Install drift",
        "",
        f"Gold objects: **{c['gold']}**. Subject objects: **{c['subject']}**. Drift: **{c['drift']}**.",
        "",
        "## Drift",
        "",
    ]
    rows = report.get("drift") or []
    if not rows:
        lines += ["None.", ""]
    else:
        for f in rows:
            lines.append(f"- `{f['object']}`: {f['kind']}")
        lines.append("")
    return "\n".join(lines)


def run_compare(gold_cn, subject_cn) -> dict[str, Any]:
    gold = dump_book(gold_cn)
    subject = dump_book(subject_cn)
    findings = diff_dumps(gold, subject)
    report = {
        "counts": {
            "gold": len(gold),
            "subject": len(subject),
            "drift": len(findings),
            "routines": sum(1 for k in gold if k.startswith("routine ")),
            "tables": sum(1 for k in gold if k.startswith("table ")),
            "columns": sum(1 for k in gold if k.startswith("column ")),
        },
        "gold": {k: v["sha256"] for k, v in gold.items()},
        "subject": {k: v["sha256"] for k, v in subject.items()},
        "drift": findings,
    }
    return report


def doctor_probe(cn) -> str:
    """Add a probe routine so the subject no longer matches gold."""
    cur = cn.cursor()
    cur.execute("DROP PROCEDURE IF EXISTS mill_audit_drift_probe")
    cur.execute(
        "CREATE PROCEDURE mill_audit_drift_probe() "
        "BEGIN SELECT 1; END"
    )
    cn.commit()
    cur.close()
    return "routine PROCEDURE.mill_audit_drift_probe"


def write_reports(report: dict[str, Any], out_json: str, out_md: str) -> None:
    if out_json:
        Path(out_json).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md:
        Path(out_md).write_text(render_md(report), encoding="utf-8")
    c = report["counts"]
    print(
        "gold={gold} subject={subject} drift={drift} "
        "routines={routines} tables={tables} columns={columns}".format(**c)
    )
    for f in report.get("drift") or []:
        print(f"{f['object']}: {f['kind']}")


def run_demo(root: Path, workdir: Path, out_dir: Path) -> int:
    basedir = default_mysqld_basedir()
    if basedir is None:
        print("no mysqld binary found (set MILL_MYSQLD_BASEDIR)", file=sys.stderr)
        return 2
    server = LocalMysqld(workdir, basedir)
    started = False
    try:
        server.start()
        started = True
        gold_cn = admin_and_db(server.connect_kwargs(), "mill_gold")
        ensure_book(gold_cn, root)
        subject_cn = admin_and_db(server.connect_kwargs(), "mill_subject")
        ensure_book(subject_cn, root)
        report_pass = run_compare(gold_cn, subject_cn)
        write_reports(report_pass, str(out_dir / "pass-report.json"), str(out_dir / "pass-report.md"))
        if report_pass["counts"]["drift"]:
            print("FAIL: freshly installed subject drifted from gold", file=sys.stderr)
            return 1
        print("pass stage: no drift")
        probe = doctor_probe(subject_cn)
        report_fail = run_compare(gold_cn, subject_cn)
        write_reports(report_fail, str(out_dir / "fail-report.json"), str(out_dir / "fail-report.md"))
        kinds = {f["object"] for f in report_fail["drift"]}
        if probe not in kinds or report_fail["counts"]["drift"] < 1:
            print(f"FAIL: doctored procedure {probe} was not reported", file=sys.stderr)
            return 1
        print(f"fail stage: detected {probe}")
        gold_cn.close()
        subject_cn.close()
        print("demo ok: install passed, doctored procedure failed")
        return 0
    finally:
        if started:
            server.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default="", help="the-mill checkout (for repo SQL / ensure)")
    p.add_argument("--host", default="")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--user", default="root")
    p.add_argument("--password", default="")
    p.add_argument("--socket", default="")
    p.add_argument("--gold-database", default="")
    p.add_argument("--subject-database", default="")
    p.add_argument("--demo", action="store_true", help="throwaway local mysqld: install, pass, doctor, fail, stop")
    p.add_argument("--workdir", default="", help="datadir parent for --demo (under the prototype by default)")
    p.add_argument("--out-json", default="")
    p.add_argument("--out-md", default="")
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when drift is found (default: exit 0 and print the report)",
    )
    args = p.parse_args(argv)

    if args.demo:
        if not args.root:
            print("--demo needs --root", file=sys.stderr)
            return 2
        root = Path(args.root).resolve()
        if args.workdir:
            workdir = Path(args.workdir).resolve()
        else:
            import tempfile
            workdir = Path(tempfile.mkdtemp(prefix="mill-install-drift-"))
        out_dir = Path(args.out_json).parent if args.out_json else Path(__file__).resolve().parent
        return run_demo(root, workdir, out_dir)

    if not args.gold_database or not args.subject_database:
        print("provide --gold-database and --subject-database, or --demo", file=sys.stderr)
        return 2
    kw: dict[str, Any] = {"user": args.user, "password": args.password}
    if args.host:
        kw["host"] = args.host
    if args.port:
        kw["port"] = args.port
    if args.socket:
        kw["unix_socket"] = args.socket
    gold_cn = connect({**kw, "database": args.gold_database})
    subject_cn = connect({**kw, "database": args.subject_database})
    try:
        report = run_compare(gold_cn, subject_cn)
    finally:
        gold_cn.close()
        subject_cn.close()
    write_reports(report, args.out_json, args.out_md)
    if args.strict and report["counts"]["drift"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
