"""Bad-value cases for every book command and argument (#238).

Each (command, dest) has a kind. The kind picks the cases: missing, empty,
unknown name, bad enum, bad format, over length. Empty is only a case for a
required argument: on an optional one it means the default. The SQL runner
(tests/server/records/test_param_matrix_sql_238.py) runs each case against a
throwaway book and expects a plain refusal, a nonzero exit, and nothing
stored, on that one call. Known gaps are in param_gaps_238.GAPS.
"""
from __future__ import annotations

import argparse

P = "c238"
LONG_NAME = "n" * 600
LONG_TEXT = "t" * 100_000
UNKNOWN = "zz238-nope"

# Base argv per book command. The runner fills placeholders per case:
#   {P} project  {N} open need  {N_CLAIMED} need this desk claimed
#   {N_PARKED} parked need  {NEWN} unused need name  {RES} unused resource
#   {HELD} resource this desk holds  {MAIL} letter to this desk
#   {ME} this desk  {PEER} another desk  {TID} todo id  {TID_LBL} todo id with {LBL}
#   {LBL} live label  {BODY} body file
BOOK = {
    "hold": ["{RES}"],
    "drop": ["{HELD}"],
    "send": ["--to-desk", "{PEER}", "--body-file", "{BODY}"],
    "reply": ["{MAIL}", "--body-file", "{BODY}"],
    "mail-thread": ["{MAIL}"],
    "mark": ["{MAIL}"],
    "trail": ["todo:{TID}"],
    "inbox": [],
    "connected": ["{P}"],
    "todo": ["{P}"],
    "create todo": ["{P}", "{NEWN}"],
    "note": ["{P}", "{N_CLAIMED}", "3/9"],
    "claim": ["{P}", "{N}"],
    "unclaim": ["{P}", "{N_CLAIMED}"],
    "unpark": ["{P}", "{N_PARKED}", "--parent-type", "todo", "--parent-id", "{TID}"],
    "assign": ["{P}", "{N}", "{PEER}"],
    "pass": ["{P}", "{N_CLAIMED}"],
    "label": ["todo", "{TID}", "{LBL}"],
    "unlabel": ["todo", "{TID_LBL}", "{LBL}"],
    "watch": ["todo", "{TID}"],
    "add": ["todo:{TID}"],
    "remove": ["todo:{TID}"],
    "score": ["{P}", "c238-kpi", "5"],
}

KIND = {
    ("hold", "resource"): "newname",
    ("hold", "doing"): "text",
    ("hold", "group_by"): "enum", ("inbox", "group_by"): "enum", ("todo", "group_by"): "enum",
    ("drop", "resource"): "name",
    ("send", "to_desk"): "name", ("send", "body_file"): "name",
    ("send", "roster"): "name", ("send", "name"): "newname", ("send", "to"): "name",
    ("reply", "mail_id"): "id",
    ("reply", "to_desk"): "name", ("reply", "body_file"): "name",
    ("reply", "roster"): "name",
    ("mail-thread", "mail_id"): "name", ("mail-thread", "after"): "int",
    ("mark", "ids"): "id",
    ("trail", "node"): "name", ("trail", "label"): "name",
    ("inbox", "limit"): "int", ("inbox", "page"): "int", ("mail-thread", "page"): "int",
    ("connected", "project"): "name", ("connected", "limit"): "int",
    ("todo", "project"): "name", ("todo", "need"): "name", ("todo", "status"): "enum",
    ("todo", "find"): "text", ("todo", "page"): "int",
    ("create todo", "project"): "name", ("create todo", "need"): "newname",
    ("create todo", "doing"): "text", ("create todo", "detail"): "text", ("create todo", "detail_file"): "name",
    ("create todo", "status"): "enum", ("create todo", "parent_type"): "enum",
    ("create todo", "parent_id"): "id",
    ("note", "project"): "name", ("note", "need"): "name", ("note", "text"): "text",
    ("note", "note"): "text", ("note", "eta"): "eta", ("note", "supersedes"): "text",
    ("claim", "project"): "name", ("claim", "need"): "name",
    ("claim", "eta"): "eta", ("claim", "msg"): "text",
    ("unclaim", "project"): "name", ("unclaim", "need"): "name",
    ("unpark", "project"): "name", ("unpark", "need"): "name",
    ("unpark", "parent_type"): "enum", ("unpark", "parent_id"): "id",
    ("assign", "project"): "name", ("assign", "need"): "name", ("assign", "desk"): "name",
    ("pass", "project"): "name", ("pass", "need"): "name", ("pass", "evidence"): "text",
    ("create todo", "done_when"): "text", ("note", "done_when"): "text",
    ("label", "type"): "enum", ("label", "id"): "cardref", ("label", "label"): "newname",  # high trust creates on first use
    ("label", "ord"): "int",
    ("unlabel", "type"): "enum", ("unlabel", "id"): "cardref",
    ("unlabel", "label"): "name",
    ("watch", "type"): "enum", ("watch", "target"): "cardref", ("watch", "hint"): "text",
    ("add", "kind"): "target", ("add", "group"): "name", ("add", "desks"): "name", ("add", "hint"): "text",
    ("remove", "kind"): "target", ("remove", "group"): "name", ("remove", "desks"): "name",
    ("score", "project"): "name", ("score", "name"): "name", ("score", "value"): "int",
    ("score", "target"): "int", ("score", "note"): "text",
    ("score", "better"): "enum", ("score", "unit"): "text", ("score", "limit"): "int",
    ("score", "at"): "text",
    # #818 PR B: --doing on every activity write; connected reads doing.
    ("send", "doing"): "text", ("reply", "doing"): "text", ("mark", "doing"): "text",
    ("claim", "doing"): "text", ("unclaim", "doing"): "text", ("assign", "doing"): "text",
    ("pass", "doing"): "text", ("note", "doing"): "text", ("unpark", "doing"): "text",
    ("drop", "doing"): "text", ("score", "doing"): "text",
    # #822: --waiting-on "WHAT [WHY]" rides --doing on the same commands.
    **{(c, "waiting_on"): "text" for c in (
        "send", "reply", "mark", "create todo", "claim", "unclaim", "assign", "pass", "note", "unpark", "hold",
        "drop", "score")},
    ("connected", "desk"): "name", ("connected", "since"): "text", ("connected", "page"): "int",
}

CASES = {
    "name": ("missing", "empty", "unknown", "over_length"),
    "newname": ("missing", "empty", "over_length"),
    "id": ("missing", "empty", "unknown", "bad_format"),
    # a todo by number or ROSTER/NEED (#274)
    "cardref": ("missing", "empty", "unknown", "unknown_name", "bad_format", "over_length"),
    "target": ("missing", "empty", "unknown", "bad_format", "bad_enum"),
    "int": ("missing", "empty", "bad_format"),
    "enum": ("missing", "empty", "bad_enum"),
    "text": ("missing", "over_length"),
    "json": ("missing", "bad_format", "over_length"),
    "eta": ("missing", "bad_format", "over_length"),
}


def bad_value(kind: str, case: str) -> str:
    if case == "over_length":
        return LONG_TEXT if kind in ("text", "json", "eta") else LONG_NAME
    if case == "bad_format":
        return {"json": "[not json", "eta": "soonish238"}.get(kind, "abc")
    if kind == "target" and case in ("unknown", "bad_format", "bad_enum"):
        # add/remove TYPE:ID (#265): a bare id, an unknown kind, an unknown id.
        return {"unknown": "todo:987654321", "bad_format": "987654321", "bad_enum": "bogus238:5"}[case]
    if case == "unknown_name":
        return "%s/%s" % (P, UNKNOWN)
    if case == "unknown":
        return "987654321" if kind in ("id", "cardref") else UNKNOWN
    if case == "bad_enum":
        return "bogus238"
    return ""


def actions(parser: argparse.ArgumentParser, command: str) -> list[argparse.Action]:
    sub = parser
    for word in command.split():
        sp = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)][0]
        sub = sp.choices[word]
    return [a for a in sub._actions if not isinstance(a, argparse._SubParsersAction) and a.dest != "help"]


_SWITCH = (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction)


def unclassified(parser: argparse.ArgumentParser) -> list[str]:
    """Book-command arguments with no kind. Must stay empty."""
    out = []
    for command in BOOK:
        for act in actions(parser, command):
            if act.dest == "office" or isinstance(act, _SWITCH):
                continue
            if (command, act.dest) not in KIND:
                out.append("%s %s" % (command, act.dest))
    return out


def _lead(base: list[str]) -> list[str]:
    lead: list[str] = []
    for w in base:
        if w.startswith("--"):
            break
        lead.append(w)
    return lead


def _strip_flag(base: list[str], flags: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for w in base:
        if skip:
            skip = False
            continue
        if w in flags:
            skip = True
            continue
        out.append(w)
    return out


def build_cases(parser: argparse.ArgumentParser) -> list[tuple[str, str, str, list[str]]]:
    """(command, dest, case, argv template)."""
    out: list[tuple[str, str, str, list[str]]] = []
    for command, base in BOOK.items():
        acts = actions(parser, command)
        pos = [a for a in acts if not a.option_strings]
        seen: set[tuple[str, str]] = set()
        for act in acts:
            kind = KIND.get((command, act.dest))
            if act.dest == "office" or kind is None or isinstance(act, _SWITCH):
                continue
            for case in CASES[kind]:
                if (act.dest, case) in seen:
                    continue
                # An explicit empty value on an optional argument means its default.
                if case == "empty" and (act.option_strings or act.nargs in ("?", "*")):
                    continue
                if act.option_strings:
                    longs = [f for f in act.option_strings if f.startswith("--")]
                    flag = longs[-1] if longs else act.option_strings[0]
                    argv = _strip_flag(base, act.option_strings)
                    argv = argv + ([flag] if case == "missing" else [flag, bad_value(kind, case)])
                else:
                    idx = pos.index(act)
                    lead = _lead(base)
                    rest = base[len(lead):]
                    if case == "missing":
                        if act.nargs in ("?", "*") or idx >= len(lead):
                            continue
                        argv = lead[:idx] + rest
                    else:
                        filled = list(lead) + [""] * max(0, idx + 1 - len(lead))
                        filled[idx] = bad_value(kind, case)
                        argv = filled + rest
                seen.add((act.dest, case))
                out.append((command, act.dest, case, argv))
    return out


def case_id(command: str, dest: str, case: str) -> str:
    return "%s %s %s" % (command, dest, case)
