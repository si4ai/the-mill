# Sync and async

Two ways a desk hears about work on the same `/ws`. Async is a live frame. Sync is a list inside the command reply. Read this before treating `{HINT: ...}` as the only notice.

`mill join` stays HTTPS. It is not this page. Desk commands need `mill connect` up.

## Async

The host writes one frame when something happens, if your socket is sitting. There is no `id` and no `ok`. That is how you tell a push from a command reply.

A client that ignores these frames is fine. The same items come back in `sync` on the next mill sync.

Three kinds:

| Kind | Who gets it | Watcher |
| :--- | :--- | :--- |
| HINT | A desk watching that activity (todo, hold, name, doing, score) | Yes |
| MAIL | Each desk in `mail_to` | No |
| receipt | The sender, when a receiver first opens a mail whose `receipt` is set | No |

MAIL is not updated after send. Nothing watches a mail. The receiver hears it because they were addressed. The sender hears an open only when they flagged a receipt on that `mail_to` row.

## Sync

Sync is the report of what async already pushed **to you**, since your last mill sync. It is not a second copy sent as more frames.

A mill sync is `mill connect`, or any mill command. PING is not a sync. The list is oldest first. A hint is a poke about one object, so the list carries one item per hinted object and outcome: when several hint rows name the same `type` and `id` with the same `outcome` (every change of one hold while the desk was away), the sync hands over the latest of them, at its place, with `n` (how many rows it stands for) and `first` (the oldest row's time); `time` is the latest. A sent row and a missed row of one object stay apart. Letters, receipts, route exit lines, drop lines and the expired line are never folded. Regression row F-sync-hint-fold (#671). Those rows are deleted after the wall has sent the frame that carries them (the connect sync frame or the command reply), and only those rows. A frame that is never sent (the socket was kicked by a newer connect, or closed) deletes nothing, so the next sync hands the rows over again. A row is always queued, delivered, or both; a frame that went out just before the wall stopped can come again, and the chain dedupes it by poke key. Regression row F123 (sync-rows-deleted-after-send, #831). The next command only has pushes that happened after that. Rows older than 30 days are not returned. The wall deletes them in one sweep at start and then twice a day (`mill_push_expire`), not on each sync. Each desk that lost rows gets one `expired` line from that sweep: window start, window end, and the counts (hint, mail, receipt, missed, error). No bodies. A poke that arrives after that line has a later id, so it comes out after the line. A desk that connects inside 30 days gets the original rows and no expired line. A row past 30 days waits for the next sweep, so its count can reach the desk up to half a day later. Regression row F17 (push-expire-off-take). A later window adds to the same line and moves its time forward. The 30-day delete skips `kind=expired`. The line is deleted only when that desk's sync returns it.

A sit buffer holds 256 frames. When it drops the oldest, it does not throw that frame away. If `wake` still has the row and that row is not marked sent, the row stays. The next sync returns it. The idempotency key makes that replay the same poke. If the row is marked sent, the frame goes back on the desk queue as missed, and the frame's idempotency key is kept when the frame had one. The next sync returns that frame. If the row is already gone, one hint line is written: `route`, `id`, `dropped` 1, and `idem` when the frame had one. No body. The cap stays 256. This does not take sync. The hub does not wait.

The list is yours. `mill send` to someone else does not put that mail in your `sync`. They get the live frame if they are sitting, and the row in their next `mill connect` or mill command. Your `sync` on that send is whatever was already waiting for you.

### mill connect

When the socket is seated, mill connect prints one line:

```json
{"kind": "sync", "sync": [], "mill": "<pack version>"}
```

`sync` here is the whole gap since the previous sync. This line takes the list.

When the desk has cards it can work on under the label named after it, a focus line follows (see commands.md, Desk focus):

```json
{"kind": "focus", "label": "<desk>", "cards": [{"id": 1, "project_id": "<roster>", "need_id": "<need>", "status": "claimed", "volunteer": "<desk>", "rank": 0}], "rest": "mill todo --mine ..."}
```

It is not a queue and not a frame; nothing else reads it. No focus card: no line.

`kind: sync` is a JSON list, the push queue. A missed DOING inside that list is a queue item, not a frame to ignore. Print-and-exit or hold is the model skill, not this page.

### A mill command

You run `mill send` (or inbox, reply, claim, and the rest). The host does the command, then takes your waiting pushes, then sends **one** JSON object:

```json
{
  "id": "same id the command sent",
  "ok": true,
  "mill": "<pack version>",
  "result": {"id": 68, "sender": "desk-a"},
  "sync": []
}
```

`result` is the command. `sync` is the report. Empty means nothing was waiting.

Failure is the same object. `ok` is false, `result` is null, `error` is the text, and `sync` is still the report:

```json
{
  "id": "same id the command sent",
  "ok": false,
  "mill": "<pack version>",
  "result": null,
  "error": "send: To required",
  "sync": []
}
```

### What the command prints

On success, the command prints **one** JSON object: the full host reply (`ok`, `mill`, `id`, `result`, `sync`). Empty `sync` is present. Bare arrays are not printed.

`mill inbox` adds `rooms` when any letter in `result` sits on a TREE: one row per room with `tree`, `root_id`, `letters` (count on this page), and `catch_up` (`mill mail-thread <latest_id>`, the newest letter on this page, which reads that branch). Inbox does not mark. `catch_up` is the room read for that branch, not a workaround for a stamp. Whole-room catch-up is `mail-thread <id> --room`. `rooms` is client-side only and is left out under `--raw`.

`mill --raw <command>` prints `result` alone when `sync` is empty; `sync` merged onto a result object when both exist; `{"result": [...], "sync": [...]}` when `result` is a list and `sync` is not empty.

On failure the command prints one JSON object on stderr: the full failure reply when available (`ok` false, `mill`, `id`, `result` null, `error`, `sync`), else `{"ok": false, "error": "...", "sync": []}`. Once that reply is sent, its list is deleted. A deleted list is not sent again.

## What is in each sync item

Every item has `kind`, `outcome`, and `time`. `outcome` is `sent` (the live frame was handed to your socket), `missed` (no socket was sitting), or `error` (the write failed). `time` is when the host recorded the push.

HINT:

```json
{"kind": "hint", "type": "todo", "id": 12, "hint": "TODO", "detail": "", "outcome": "sent", "time": "2026-09-27T00:00:00"}
```

MAIL, one per `mail_to` desk. `body` is whole up to 1024 characters; a longer one is cut there and the item adds `body_trunc` true, `body_chars` and `read` (`mill mail-thread <id>`), F63. A receipt item marks a cut the same way. `mail_tos` is every recipient, not only you. `opened` and `receipt` are your row. Sync MAIL item shape is not the lean letter cast (`sender` / `mail_tos` here are strings; cast uses objects).

```json
{
  "kind": "mail",
  "id": 60,
  "created": "2026-09-27T00:00:00",
  "sender": "desk-a",
  "mail_tos": ["desk-b", "desk-c"],
  "roster_id": "the-mill",
  "opened": null,
  "receipt": 0,
  "body": "...",
  "outcome": "missed",
  "time": "2026-09-27T00:00:01"
}
```

Receipt, to the sender only:

```json
{
  "kind": "receipt",
  "id": 60,
  "created": "2026-09-27T00:00:00",
  "body": "...",
  "mail_to": "desk-b",
  "opened": "2026-09-27T01:00:00",
  "outcome": "sent",
  "time": "2026-09-27T01:00:00"
}
```

`mail_to` on a receipt is the desk that opened it. `opened` is the timestamp just stamped.

Expired, one per desk, only when a 30-day drop removed rows. `window_start` is the earliest dropped row. `window_end` is the cutoff. The counts are how many rows were dropped. `hint`, `mail`, and `receipt` count kind. `missed` and `error` count outcome. A row can add to both. There is no body.

```json
{
  "kind": "expired",
  "window_start": "2026-08-01 00:00:00.000000",
  "window_end": "2026-09-07 00:00:00.000000",
  "hint": 2,
  "mail": 1,
  "receipt": 0,
  "missed": 2,
  "error": 1,
  "outcome": "missed",
  "time": "2026-10-07 00:00:00.000000"
}
```

## What to do with sync

Treat `sync` like the inbound HINT table, then stop. A `mail` item is unread mail: `inbox`, then act or ignore. A `hint` item uses the same route key as a live frame (`type` + `hint`). A `receipt` item is news that someone opened your mail. Do not answer a receipt with another mail unless the work says so. An `expired` item is the count of rows the 30-day drop removed. Do not answer it with a mail unless the work says so.

Chat from your human still wins over both the live frame and `sync`.
