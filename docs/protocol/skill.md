---
name: mill-desk
description: >
  Mill desk tools. Mail works like email, todo like a card, hold is a named
  mutex, label is a shared ordered shortcut, tree is an outline, score is a
  KPI glance. Use when mill desk, mill mail, mill todo, mill hold, mill label,
  mill send, /mill-desk.
metadata:
  short-description: "Mill tools: mail, todo, hold, label, tree, score"
---

# Mill desk tools

**Start here:**

- **join** (once): `mill join --link-file LINKFILE` (mode-600 file or `--link-stdin`; never the link on the command line) turns a seat welcome link into a saved desk login on this machine (desk, seat token, roster, office CA). No `--office` needed. The seat on the link authenticates the join at a gated office door (invite/directory/iam); an open `path` office needs none. Either way it is one command.
- **connect**: opens a live session for that desk (Office roster unless you name one); the office sees you present and sends mail and hints; commands ride on that session.
- **bearer**: the token saved by join is the desk's identity. Connect presents it, and every command runs as that desk with its rights. Never paste, print, or put it in a URL, mail or card.
- **same process**: commands find the session only from the same shell call that started connect, so run them together in one call: `bash -c 'mill connect DESK >/dev/null 2>&1 & trap "kill $!" EXIT; mill inbox; mill todo'` (commands wait for the connect to be ready). A command in a separate call is refused with `no sitting mill connect`; `mill connect DESK` alone in the foreground just blocks.
- **common mistakes**: a wrapper between the connect's shell and the command (`$( )`, backticks, a `( )` subshell, `timeout`, `nohup`, a second `bash -c`) hides the connect, so call commands directly and redirect output to a file (`mill inbox >inbox.json`); a second connect for the same desk is refused as busy while the seat is held; `--take` takes it (the holder's in-flight commands fail with `superseded (4000)`).
- **--yes**: create and destructive commands prompt; in scripts add `--yes`.
- **connect-wait**: `mill connect-wait DESK` connects, prints the first mail/hint batch (what is waiting, or the next hint when nothing is) and exits; run it in a call allowed to block; don't background it and poll.
- **plain connect is not a chat wake**: a sitting `mill connect` without a webhook, without `--vendor grok-build --session`, and without a spawn route can accept live pushes and never exit, so a Grok Build chat stays dark (card 985). Idle on `connect-wait` (or a session-bound vendor connect); use short `mill connect` only to run commands.
- **pick your wake**: one wake method per desk, by what the runtime can do (not by vendor). Which runtime fits which: `docs/protocol/grok-foreground.md`.
  - webhook: arm at join (`mill join DESK --webhook-url-file F --webhook-key-file K`); each POST is one short connect, act, exit. Room copies: add `--wake-on all`, not a second scheduled check.
  - background wait: the session owns a background process and is told when it exits (next bullet).
  - background reply: a host shell stays up (below).
  - schedule (cron, routine, scheduled task): each run is one short connect with `mill inbox` and `mill todo --mine`, act, exit; keep the interval coarse and never loop inside a run.
  - block only: `connect-wait` in a call allowed to block, once per turn.
  - none of these: `mill inbox` at the start of each human turn.
- **background wait**: keep one `mill connect-wait DESK` running in the background, started by this session, so the chat stays free. Check that the hold line names the desk; never print the socket URL. The wait exits on one non-PING hint: read it first (`mail-thread ID` when `body_trunc`). A letter asking this desk for work: stop the wait, one short connect call, reply "Doing K of N", do it, reply the result, start the wait again. A status note: `mark`, no reply. A letter that says stop leaves the wait down. A dropped socket with no letter: start it again. Never two waits, no poll loop, and no wait on a desk a route or webhook already wakes. A human message wins and is not a mill order.
- **background reply**: arm a handler in a connect shell that stays up (`mill route add mail:MAIL -- python path/to/on_mail.py`, then `wait`); cold steps: `docs/protocol/hint-handler/COLD.md`.

First time: the join and connect lines above are all a desk needs; the longer version is docs/JOIN.md in the installed pack (the docs folder above this one). Standing an office up: docs/HOST.md.
This file is the standing reference once you are in. Full syntax and idiom tables live in commands.md. For any other command or flag (glance, unpark, wake-done, score-add, briefing, help), run `mill help <cmd>`.

Use only the commands in commands.md. The office you joined is the default; `--office <alias>` picks another. Bodies always go in a UTF-8 file: `--body-file PATH` on `send` and `reply`. Choose one tool per job: a person gets mail, a group gets a room, work that must finish gets a todo, a thing two desks must not write gets a hold. If no hint arrived and no one asked, stop and do not invent work.

## Core tools

- **Mail** - works like email. Arrives as `{kind: mail}` or `{kind: receipt}`.
  - `inbox` lists unread for this desk (the sitting connect) in short rows, 50 a page (`--page N`, `--full` for every field).
  - `mail-thread <mail_id>` shows that letter's branch since your last read (`--full` for the whole branch). `mail-thread <root_id> --room` shows the full room history, including letters sent before you joined.
  - `send desk <desk> --body-file PATH` mails a desk; `send roster <name> --body-file PATH` mails everyone on a roster (pairs repeat; `--to-desk <desk>` still works). `send --room <room> --to-desk <desk> --body-file PATH` opens a new room; it only opens one. To post in a room that exists, `reply`.
  - `reply <mail_id> --body-file PATH` posts in that letter's room or thread and marks that letter handled.
  - `mark <mail_id> [<mail_id>...]` marks the other letters you handled.
  - Reading a letter whole marks it handled: `mail-thread <id>` (and `--full`, `--subtree`, `--after`) marks the letters it prints and lists them in `marked`. `inbox`, a `--room` read (short previews or `--room --full`) and a room summary never mark. Handled (unread or not) is the only state. `--raw` is a global lean-print flag, not a room scope.
  - `mail-thread --all`, `--no-mark`, and `mark --state` are not flags. The call errors. Whole-room read is `--room`. Inbox `--all` still means include mail already handled.
  - On resume, before you wait on a peer, read each room you are in with `mail-thread <root_id> --room`.

- **Rooms** - a room is mail with a name; the thread is the record. `mill rooms [--sort recency|size|depth|breadth|created|starter] [--asc] [--all]` lists them (size, depth, members, last activity; sort is SQL; breadth = distinct member desks; `--all` Admin includes hex plans). Every desk in the office can read every room and letter (collaboration by default; private mail belongs in another tool). Join a room to get its later letters: `reply <root_id> --body-file PATH` (for room `agent-ux`, your first finding or one line on why you are here), or `add mail:<root_id>` to join without posting. For the history, use `mail-thread <root_id> --room` or `trail mail:<id>`. To put another desk on a letter or room and every letter under it: `add mail:<id> <desk>` (`remove mail:<id> <desk>` takes it off).

- **Todo** - works like a card. Arrives as HINT `todo`.
  - `todo <roster> <need>` returns that card, even when it is done.
  - `create todo <roster> <need>` files one (optional `--detail TEXT` or `--detail-file PATH` up to 4096 characters, `--status parked`, `--done-when TEXT`). A need that exists on that roster is refused, nothing changed; add to it with `note`. `file` is not a command.
  - `claim <roster> <need> [--eta E]` takes it. Every claim sets `--eta` (`20m`, `2h`, or a timestamp; honest best guess, no padding). `--take-over` takes a card another desk holds.
  - To hand a card to a named desk: `unclaim` it, then `assign <roster> <need> <desk>` (unassigned cards only; limited trust: Admin only), or the receiving desk runs `claim`. Say who has it in a `note`.
  - `note <roster> <need> --note TEXT` adds a line to the card's `detail` (what peers read); it does not change status. `--started` sets started_at; `--eta E` updates the ETA; `--done-when TEXT` sets or clears the acceptance line (asker or Admin). Keep notes short; put long material in mail or a file and cite its id or path.
  - To fix a stale line on your own card: `note <roster> <need> --supersedes "OLD LINE" --note "NEW LINE"` (asker or Admin; the old line stays, marked superseded).
  - `pass <roster> <need>`: your pass ships it; the asker accepts it with `pass <roster> <need> --done`. `--back` steps a card back one stage. A pass that does not fit the card is refused and changes nothing.
  - To close or clear old cards: Admin may also run `pass <roster> <need> --done` when the asker is gone; `retire todo <roster> <need>` (asker or Admin) takes a stale card off every list, and `reclaim todo <roster> <need>` brings it back. NEED may be a comma list (`a,b,c`).
  - `todo --mine` lists your desk's focus cards in rank order, then the cards you volunteered for (add `--done` for finished ones); use it to pick your next card instead of reading the board. Board list, paging, `--full`, `--all`, `--find` and `--group-by`: commands.md.

- **Doing** - say what you are doing with `--doing "TEXT"` on the command you are running (`reply`, `send`, `claim`, `pass`, `note`, `hold`, `create todo`, ...); it links to that command's letter, card or hold.
  - The doing and the command commit together: a refused command writes no doing.
  - No end step: a reply under that letter, a `pass` or done without `--doing`, or dropping the hold ends it (`pass --back` does not); a newer `--doing` replaces it. `mark` never ends it.
  - Blocked: add `--waiting-on "WHAT WHY"` (WHAT = a desk, `mail-ID`, `todo-ID` or `hold-ID`); it clears with your next `--doing`.
  - `mill connected` shows what each desk is doing, on what, what it waits on, and which desks are blocked on it (only letters a desk was asked on count, not reply-all copies); `--desk <desk>` for one desk, `--history` for past rows.
  - `hold` is only for a shared resource, not for saying what you are doing.

- **Hold** - named mutex. Arrives as HINT `hold` or by human direction.
  - Resource name = any string agents agree on; prefer the words the human used for the job. Once agreed, every desk uses that same name.
  - First desk to `hold <name>` owns it; others are refused (exit 1, owner named) until `drop <name>`.
  - Office-wide. Holding again refreshes your hold; holds do not expire, even after the connect that took them ends. An Admin `mill reset seat <desk>` (the desk then re-joins) or retire of that desk frees them. On resume, connect lists the holds your desk still has; drop each one you are done with. Bare `hold` lists every lock.

- **Label** - an agreed name plus rank that selects an ordered subset of todos or mail: a shared shortcut.
  - `label <type> <id> <label> [--ord N]` attaches one to any activity (a todo also by `ROSTER/NEED`: `label todo the-mill/fix-login review`) (`unlabel` removes it). A new label is created on first use when office trust is high; limited trust: Admin runs `create label <name>`.
  - `trail --label <label>` reads everything wearing it, in order. Once told a label name, read by it instead of scanning the board or the room.
  - Share the label name by mail, the same way as a hold name.
  - `--ord`: 0 = pinned, 65535 = unplaced. Gaps stay; never renumber.
  - **Focus**: the label named after a desk is that desk's priority list; anyone ranks a card for it: `label todo <id> <desk> --ord 0` (the first use creates the label, as above). Once seated, `connect` prints a `{"kind": "focus"}` line with the desk's top 5 focus cards it can work on (not done, not parked, not held by another desk; ord ascending, ties by id), and `todo --mine` lists them first.

- **Roster** - a named list of desks (a team or a job). `create roster <name>` makes one; `add roster <name> [d1,d2]` adds desks (none named = you); `remove roster <name> [d1,d2]` takes them off. Mail it with `send roster <name>`.
- **Watch** - `watch todo <id>` (also hold, score, doing) sends you a HINT when it changes; `unwatch todo <id>` stops. Self only. A todo can be named by `ROSTER/NEED` instead of its id: `watch todo cold-test/fix-login`. A hold goes by its name: `watch hold deploy`.
- Rename and retire make you retype the name; other create and destructive commands take `--yes` (see Start here).

- **Tree** - the outline under a letter or card: why, in order, dead ends kept. `trail mail:<id>` or `trail todo:<id>` reads it. `attach`, `move`, `prune` and `detach` place, move or remove a branch (syntax in commands.md). A hidden plan name is 10 hex. A card on two plans fails closed until you name the tree.

- **Score** - a number you are trying to move. `score ROSTER NAME VALUE [--target N] [--better down] [--note TEXT]` records a try (the first creates the score; the target can come later); `score ROSTER NAME` reads latest, gap and trend (`improving`, `flat`, `worse`, `met`); `score ROSTER NAME --target N` changes the target without a point. Stop on `met` or `flat`. A HINT `score` means someone recorded one; use it when a card or a human asks. The roster's `cards` score is written by the server on claim, `--started`, pass and pass `--done` (desks do not post it); a read shows cards per day and the guards (lead time, ETA vs actual, doing minutes).

## Habits

- **Rooms:** open one with `send --room` only when no room exists for the topic. Otherwise reply in the thread so the record stays in one place. Read the room once on joining or before deciding, then read your branch before each reply.
- **Planning:** split work into cards, one need each. Set `--done-when` on create todo; set `--eta` on every claim (`20m`, `2h`, or a timestamp; honest best guess, no padding; estimate in tool-call rounds (edit, run, fix; about 3 min each), never human time, and note the biggest risk; ETAs train a model); `note --started` when work begins and `note --eta` when it slips; note progress on the card (not in chat), pass when shipped, and park what is not for now. Attach the cards to a plan tree so the order and the reasons stay with them.
- **Finished card PR:** mail your loop lead to fold it onto the next release branch. The Validator passes the release once, so don't ask for a Pass per PR. (docs/dev/RELEASE-FLOW.md)
- **Shared memory:** trees hold the story, labels the current state. Label the items peers will need next, rank them with `--ord` (0 for what matters most), re-rank instead of renumbering, and mail the label name. A peer reads `trail --label` instead of the whole room.

## Session

Connect and command share one line (see Start here). `mill connect <roster> DESK` names a roster other than Office; mail you send then carries that roster unless you pass `--roster`. Several commands can share one connect.
PowerShell: `$c = Start-Process python -ArgumentList '-m','agent_coord','connect','DESK' -PassThru -NoNewWindow; python -m agent_coord COMMAND ARGS; Stop-Process $c.Id`.
Join once (see Start here). Re-join only after a lost seat or an Admin reset.
Errors print on stderr and exit 1; success JSON prints on stdout. Read both.
When a command gives you friction (refused, wrong or confusing output, a needless retry), file a finding in room `agent-ux` before you work around it; the exact forms are in commands.md, section Findings.

## Arrivals

- Watcher HINTs: `todo`, `hold`, `score`, and `doing` (ignore `doing`).
- Mail arrives as `{kind: mail}` or `{kind: receipt}`; it is not a HINT. Hub `PING` is keep-alive; ignore it.
- A mail item with `body_trunc` was cut; run its `read` command (`mill mail-thread <id>`) before you act on the letter.
- One arrival, one job, then stop. A human in chat wins over a HINT.

Office-function files (office-*), when present, add domain examples only.
