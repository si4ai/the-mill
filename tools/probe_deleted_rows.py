# -*- coding: utf-8 -*-
"""Make deleted todo and score rows live, on throwaway fixture rows only (#160).

There is no delete verb (verb freeze). This tool sends the test-only
probe-delete RPC over the sitting mill connect. The office refuses any row
that is not in a t-<8 hex> fixture project or was not made by the calling
desk, so real cards and other desks' rows cannot be touched.

  probe_deleted_rows.py run [--project t-<8 hex>]
      open one card and write one score in a fixture roster, probe-delete
      both, then read the card back with trail and print what to check on
      the Wall. By default the tool makes a fresh t-<8 hex> roster first
      (0.7 rosters must exist before a card or score can use them) and
      retires it at the end, also after a refusal; --project names a
      roster you made, which the tool leaves alone.
  probe_deleted_rows.py delete --type todo|score --id N
      probe-delete one of your own fixture rows.

Run it as a child of the shell that started mill connect, with the python
that has the mill pack installed:

  bash -c 'mill --office ALIAS connect DESK >/tmp/c.log 2>&1 & CP=$!; sleep 8;
           python tools/probe_deleted_rows.py run; kill $CP'

Needs an office at 0.6.30 or later (older offices answer unknown mill verb).
Making the roster and retiring it need an Admin desk on a limited-trust office.
A non-Admin run still prints the probe result; roster.retired is false and
roster.reason names the refuse (card 721). Exit 0 when the probe rows are
deleted even if retire was refused; exit 1 when the probe itself failed; 2 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from typing import Any, Callable

FIXTURE = re.compile(r"^t-[0-9a-f]{8}$")
VERB = "probe-delete"


def _default_call(body: dict[str, Any]) -> Any:
    from agent_coord.client.ws import mill_ws_call

    return mill_ws_call(body)


def _result(reply: Any) -> Any:
    if isinstance(reply, dict) and "result" in reply:
        return reply["result"]
    return reply


def _first(res: Any) -> dict[str, Any]:
    if isinstance(res, list):
        return dict(res[0]) if res else {}
    return dict(res or {})


def fresh_project() -> str:
    return "t-" + secrets.token_hex(4)


def delete(call: Callable[[dict], Any], typ: str, rid: int) -> dict[str, Any]:
    return _first(_result(call({"verb": VERB, "type": typ, "id": int(rid)})))


def make_roster(call: Callable[[dict], Any], project: str) -> None:
    call({"verb": "roster", "slug": project, "confirm": project, "yes": True})


def retire_roster(call: Callable[[dict], Any], project: str) -> None:
    call({"verb": "retire", "slug": project, "confirm": project, "yes": True, "name_type": "roster"})


def run_own_roster(call: Callable[[dict], Any], project: str) -> dict[str, Any]:
    """#644 / #721: make the fixture roster, run, then retire it even after a refusal.

    Retiring the roster needs Admin on a limited-trust office. When retire is
    refused, still return the probe result and set roster.retired false with
    the refusal reason (card 721); do not drop trail_state behind a bare error.
    """
    make_roster(call, project)
    run_err: BaseException | None = None
    out: dict[str, Any] | None = None
    try:
        out = run(call, project)
    except BaseException as e:
        run_err = e
    retired = False
    reason = ""
    try:
        retire_roster(call, project)
        retired = True
    except BaseException as e:
        reason = str(e)
    roster = {"made": True, "retired": retired, "slug": project}
    if not retired:
        roster["reason"] = reason
    if out is None:
        # Probe itself failed: still surface the roster slug and retire
        # reason so a non-Admin desk is not left with only "todo: refused" (#721).
        assert run_err is not None
        return {"ok": False, "error": str(run_err), "roster": roster, "project": project}
    out["roster"] = roster
    return out


def run(call: Callable[[dict], Any], project: str) -> dict[str, Any]:
    if not FIXTURE.match(project or ""):
        raise ValueError(f"project must be t-<8 hex>, got {project!r}")
    tag = project[2:]
    need = f"probe-deleted-{tag}"
    kpi = f"probe_deleted_{tag}"
    card = _first(
        _result(
            call(
                {
                    "verb": "open",
                    "project": project,
                    "need": need,
                    "detail": "test-only row for the #160 deleted-rows probe; safe to ignore",
                }
            )
        )
    )
    tid = int(card.get("id") or 0)
    if tid <= 0:
        raise RuntimeError(f"open gave no card id: {card!r}")
    sc = _first(_result(call({"verb": "score", "project": project, "name": kpi, "value": "1"})))
    sid = int(sc.get("id") or 0)
    if sid <= 0:
        raise RuntimeError(f"score gave no id: {sc!r}")
    gone_t = delete(call, "todo", tid)
    gone_s = delete(call, "score", sid)
    trail = _result(call({"verb": "trail", "node": f"todo:{tid}"})) or {}
    nodes = trail.get("nodes") if isinstance(trail, dict) else None
    trail_state = ""
    for n in nodes or []:
        if str(n.get("kind")) == "todo" and int(n.get("id") or 0) == tid:
            trail_state = str(n.get("state") or "")
    ok = gone_t.get("state") == "deleted" and gone_s.get("state") == "deleted" and trail_state == "deleted"
    return {
        "ok": ok,
        "project": project,
        "todo": {"id": tid, "need": need, "state": gone_t.get("state"), "deleted": gone_t.get("deleted")},
        "score": {"id": sid, "kpi": kpi, "state": gone_s.get("state"), "deleted": gone_s.get("deleted")},
        "trail_state": trail_state,
        "check": [
            f"trail_state above: mill trail todo:{tid} reads the card as deleted",
            f"Wall Wire (signed in): rows todo {tid} and score {sid} show the deleted pill",
            "Wall History: both rows show the deleted pill",
        ],
    }


def main(argv: list[str] | None = None, call: Callable[[dict], Any] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="probe_deleted_rows.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="make and delete one fixture card and one fixture score")
    r.add_argument("--project", default="", help="your fixture roster t-<8 hex> (default: a fresh one the tool makes and retires)")
    d = sub.add_parser("delete", help="probe-delete one of your own fixture rows")
    d.add_argument("--type", required=True, choices=("todo", "score"))
    d.add_argument("--id", required=True, type=int)
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    call = call or _default_call
    try:
        if args.cmd == "run":
            project = args.project or fresh_project()
            if not FIXTURE.match(project):
                print(json.dumps({"ok": False, "error": f"project must be t-<8 hex>, got {project!r}"}))
                return 2
            out = run(call, project) if args.project else run_own_roster(call, project)
        else:
            out = delete(call, args.type, args.id)
            out["ok"] = out.get("state") == "deleted"
    except Exception as e:  # CoordError from the office, or a bad reply
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps(out, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
