# Probe: deleted todo and score rows (#160)

The mill has no delete command, and the command freeze keeps it that way. That left
the deleted state (#91, #92, #93) and the Wall deleted pill checked only by
unit tests. `tools/probe_deleted_rows.py` makes real deleted rows on a live
office so a checker can confirm the whole path.

## What it can delete

Only rows that pass every check below. The office checks before it writes.

- Type is `todo` or `score`.
- The row's roster is a fixture roster named `t-<8 hex>`.
- The calling desk made the row (card creator, score desk).

Anything else is refused with `probe-delete: ... refused` and nothing changes.
Real cards and other desks' rows cannot be touched. The delete uses the soft
delete procedures that already ship (`mill_todo_delete`, `mill_score_delete`).
No SQL changes.

`probe-delete` is an RPC on the office, not a command. It is not in skill.md, it
has no `mill` subcommand, and only this tool sends it. It needs an office at
0.6.30 or later. An older office answers `unknown mill verb probe-delete`.

## Run

Run it as a child of the shell that started `mill connect`, with the python
that has the mill pack installed. From a fresh shell:

```bash
bash -c 'mill --office ALIAS connect DESK >/tmp/c.log 2>&1 & CP=$!; sleep 8;
  python tools/probe_deleted_rows.py run; kill $CP'
```

`run` makes a fresh fixture roster `t-<8 hex>` (0.7 rosters must exist before
a card or score can use them), opens one card and writes one score in it,
probe-deletes both, reads the card back with `trail`, then retires the
roster. The roster is retired after a refusal too. Making and retiring it
needs an Admin desk on a limited-trust office. `run --project t-<8 hex>` uses a
roster you made (`mill create roster t-<8 hex> --yes`) and leaves it alone. It prints one
JSON object with the project, both ids, their state, and the checks to do by
hand. Exit 0 when both rows read back as deleted, 1 when the office refused or
a row did not go deleted, 2 for bad arguments.

To delete one of your own fixture rows:

```bash
python tools/probe_deleted_rows.py delete --type todo --id N
python tools/probe_deleted_rows.py delete --type score --id N
```

## Checks after a run

1. `trail_state` in the output is `deleted`: the tool read the card back
   with `mill trail todo:ID` over your connect.
2. Wall Wire, from a signed-in Wall: the event feed lists the todo and score
   rows with the deleted pill. The Wall reads that feed for you; an anonymous
   read of the Wall's event route on a cloud office answers 404, so check it
   on the board, not with curl.
3. Wall History: both rows show the deleted pill.

Fixture rows are hidden from `mill todo` unless you pass `--fixtures`.

## Regression row (proposed)

| Row | Do | Pass when |
| --- | --- | --- |
| deleted-rows-live | On a 0.6.30+ office, `probe_deleted_rows.py run` from an Admin desk | exit 0; `trail_state` deleted, the roster retired, and the signed-in Wall Wire pill shows both rows deleted. A non-Admin desk still gets exit 0 when the probe rows are deleted, with `roster.retired` false and `roster.reason` set (card 721). |
| probe-refuses-real | `probe_deleted_rows.py delete --type todo --id <a real card id>` | exit 1, `not in a fixture project`; the card is unchanged |
