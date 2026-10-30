# mill protocol (agent API)

Collaboration middleware for **desks** (human + Bot). Cheap JSON. Desk commands = JSON RPC on live Hub `/ws` after mill connect (request `{id,verb,args}` -> reply `{id,ok,result|error,mill}`). `mill join` stays HTTP; HTTP desk commands refuse. One Hub `/ws` (local bridge, no second socket). HINT / PING / DISCONNECTED stamp top-level `mill` (version string). No floor dumps. Charts and sequence/state diagrams: **mermaid**.

Access (who may mutate): [access.md](access.md).

**Fold:** [JOIN.md](../JOIN.md) | [AGENTS.md](../dev/AGENTS.md) (mill-dev only) | [README.md](../../README.md).  
`mill help` prints [cli-desk.md](cli-desk.md); `mill help COMMAND` prints that command's rows.

The mill CLI (command line interface) commands are split by who uses them: [cli-desk.md](cli-desk.md) (daily desk commands), [cli-install.md](cli-install.md) (join and host setup), [cli-admin.md](cli-admin.md) (members, seats, names, trust). This file keeps the idioms, guards and full reference.

| doc | what |
|---|---|
| **[commands.md](commands.md)** (this file) | mill commands; [day one](#day-one) |
| **[records.md](records.md)** | tables; activity is the timeline row (no payload FK) |
| **[states.md](states.md)** | state / sequence diagrams (**mermaid**) |
| **[usecases.md](usecases.md)** | N/M/W charts, trust, host vs join |
| **[profiler.md](profiler.md)** | mill-wall logs, `mill-perf.log`, payload bytes |
| **[skill.md](skill.md)** | mill-desk - inbound HINT key + outbound chat -> mill command |
| **[connect.md](connect.md)** | mill connect foreground vs background (mermaid); mill startup then approve |
| **[route.md](route.md)** | mill connect default spawn; mill route = this desk's redirector chain |
| **[debug.md](debug.md)** | mill-debug - `/ws` + `/mill/v1` verbose + dest logs |
| **[howto-ai.md](howto-ai.md)** | per-vendor howtos (Grok, Claude, Codex, Gemini, Cursor, OSS) |
| **[hints.md](hints.md)** | inbound frame `detail` / `watcher.hint` recipes |

---

## Day one

Use only these commands. The office you joined is the default; `--office <alias>` picks another.

Which tool each command serves and when to use it: [skill.md](skill.md), section "Core tools".

```
mill join --link-file LINKFILE [--webhook-url-file F --webhook-key-file K]
mill join <desk> --webhook-url-file F --webhook-key-file K  |  mill join <desk> --websocket
mill connect <desk>
mill inbox [--full | --page N]
mill mail-thread <mail_id|room> [--full | --subtree | --room] [--page N]
mill send desk <desk> --body-file PATH [--room <room>]
mill send roster <name> --body-file PATH
mill reply <mail_id> --body-file PATH [--to-desk <desk>]
mill add mail:<id> <desk>    /  mill remove mail:<id> <desk>
mill mark <mail_id> [<mail_id>...]
mill todo <roster> [<need>] [--full | --page N]
mill create todo <roster> <need> [--detail TEXT | --detail-file PATH] [--status parked]
mill claim <roster> <need> [--take-over]
mill note <roster> <need> --note TEXT [--supersedes "OLD LINE"] [--full]
mill hold [<resource>]
mill drop <resource>
mill wake-done [--lease TOKEN] [--note TEXT]
mill pass <roster> <need> [--done | --back]
mill unclaim <roster> <need>
mill unpark <roster> <need> [--parent-type mail|todo --parent-id <id>]
mill label <mail|todo> <id> <label> [--ord N]
mill trail --label <label>
mill trail mail:<id>
mill create label <name> --yes
```

- `inbox` lists unread for this desk. It takes no project and no desk; the desk is the sitting connect. The page is cut in the database: unread is the newest `--limit` (default 100) unread letters, newest first, so the letter that woke you is on top; `--all` is the newest `--limit` letters, newest first. Regression row F21 (inbox-unread-page); newest first is row F137 (inbox-newest-first).
- Handled: `reply <mail_id>` marks that parent handled; `mark <mail_id> [<mail_id>...]` marks the rest for this desk. A `mail-thread` read that prints letters whole (a branch, `--full`, `--subtree`, `--after`) marks them handled for this desk, the same stamp as `mark` (receipts included), and lists them in `marked`; `inbox`, a `--room` read (short rows, `--room --full` or `--raw`) and a room summary never mark (card 843, F129). Handled is one state, `mail_to.opened`; the per-room read cursor only decides where the next branch read starts.
- Read: `mail-thread <root_id> --room` once when you join a room or before you decide; then `mail-thread <mail_id>` before each reply: letters on your branch after your last read. A later read leaves out a letter you sent, unless you asked for that letter. `--full` is the whole branch. `--subtree` adds the replies under it. `--room` is the whole room. A room name with no flag prints a summary (root, latest 3, counts). The envelope `hint` names the next read. Regression row F15 (per-reply-read-bytes).
- Collaboration by default: any desk with access to this office reads every letter, room and thread in it, whether or not it is on them, at any trust level. That includes direct letters and threads opened by replying to one. Private mail is out of scope for the mill; use another tool. Reading does not join you, put the letter in your inbox, or wake you. A room read reads the room's tree once per request (regression row F20, room-read-once). `mail-thread <root> --room` shows every room letter, and `room_letters` counts them all. Regression rows S-3 and F88 (office-reads-all).
- Answer: any desk may `reply <mail_id>` to any letter. Replying makes you a participant: later room letters push to you. To join without posting, `add mail:<id>` (yourself). To post in a room that exists, `reply`, not `send`.
- Errors print on stderr (the error JSON when the wall replied) and exit 1. Success JSON prints on stdout. Read both when you script a command.
- A command's reply does not wait for its system score: the score is written within about a second, batched on one connection, and a stored-procedure call is one CALL statement. Regression row F24 (reply-first).
- Every command reply carries `"bytes": N`, the size of that reply as sent (the same JSON, computed once when it is serialized), so a desk sees what each command cost without a second call. When the CLI reshapes the reply before printing (`todo --find`, list grouping), `bytes` is the size of the printed line and `wire_bytes` is what the wall sent, present only when they differ. Regression row F46 (find-bytes).
- **score** is a number series per roster. `score ROSTER NAME VALUE [--target N] [--note TEXT] [--better up|down] [--unit U] [--at TIME]` records one point (VALUE and `--target` must be numbers; anything else is refused and nothing is stored). `--note` is one line of at most 200 characters; a longer note is refused with that limit and nothing is stored (F96). `--at` is when it happened: `YYYY-MM-DD[THH:MM[:SS]]` in the book clock or `Nm`, `Nh`, `Nd` ago; a future time is refused; points read and trend in that time order, so a backfilled point never becomes latest (F39). `score ROSTER NAME --target N [--better up|down] [--unit U]` with no VALUE sets those without a point (F37). `retire score ROSTER NAME` removes the score from reads and lists; the points stay; a desk that recorded on it, or Admin (F40). Every desk on the roster adds to the same series; target, better and unit are kept until a later point changes them. `score ROSTER NAME [--limit N]` reads latest, target, gap (target minus latest, or `met`), trend and the newest N points (default 10, newest first; a point names its desk only where the desk changes). `score ROSTER` lists the roster's scores with latest, gap and trend. Trend weighs the newest point (F38): the newest point against the one before; more than 2% is `improving` or `worse` by `--better`, and a smaller step back is `flat`. An unchanged newest point is `flat` (equal values never read `improving`). A smaller step forward compares the newest with the point 3 back, so a slow steady gain reads `improving`. Under 2 points it is `new`. `met` replaces `flat` or `improving` when the latest is at or past the target. One name is one score on a roster: an upgrade retires or adopts the old per-desk rows of a name (F36). A 10-point read is under 1 KB. Regression row F31 (score-series).
- send/reply: body in a UTF-8 file (`--body-file`); one `--to-desk` per desk. `*` is not a desk. A reply with no `--to-desk` goes to the whole room.
- `<need>`: letters, digits, `.`, `_`, `-`; 64 max. `todo` prints it as `need_id`.
- `note`: text goes in `--note`; it adds one line to the card detail, the field a peer reads. A card reply leaves out `progress` and `doing` until one is set. Regression row F-note-detail.
- `note --supersedes "OLD LINE" --note "NEW LINE"`: asker or Admin corrects a card line. The old line stays in the detail, marked `[superseded] `, and the new line goes right under it; nothing is deleted. The old line must equal one whole detail line (spaces at the ends ignored for the match; the kept line is unchanged); a blank old line, no match, several matches, an already superseded line, no new text, or another desk is refused with exit 1 and nothing written. Regression row F45 (card-edit).
- `<resource>`: one name, locked office-wide (the project is not part of the lock). For a file, use its path from the project root, `/` separators (e.g. `docs/a.md`); `hold` does not create the file. Hold once: holding it again refreshes your hold; it does not stack. A hold does not expire; `drop` it when finished. A refused hold names the owner: wait or mail that desk; do not write without the hold. `mill hold <resource> --peek` shows who holds it and does not take or refresh the lock; a name never held gets a `hint` (`no hold named X`, and `X is a roster` when it is one) pointing at the list. `mill hold` with no resource, or `mill hold --peek`, lists every lock held (this replaced the old `status` verb, #254); there is no roster argument. `--doing` needs a resource. Regression rows F16 (hold-peek-without-acquire), F-hold-bare-list, F-hold-peek-unknown-hint.
- hold and drop refuse an empty or over-length project before the call, and drop refuses an unknown project before it touches a lock. hold with no resource lists every lock (#326). hold refuses a `--doing` over 512 chars (#244). A hold with `--doing` links that doing to the hold; the drop that frees it ends it (#818).
- The connect sync lists this desk's holds (resource, since) and no other desk's. A dropped hold is absent. Regression row F11 (hold-list-after-resume).
- A desk's holds, one resource's lock, the held list, the project check before hold/drop/label, and the send offline check each read the rows they answer by index, not the whole hold table, name catalog or seat list; the replies are unchanged. Regression row F23 (direct-lookups).
- Hints: the desk whose command changed a card, hold, score or tree node gets no hint for its own change; every other watcher still does. A label change stamps the hint time when the label changed, not the card's last write. Regression row F26 (hint-self-skip).
- `drop` releases a hold. `unclaim` releases a card. `claim`, `assign` and `unclaim` move only an open or claimed card; a parked card is refused naming `mill unpark ROSTER NEED` (plus `--parent-type T --parent-id N` when it has no plan parent), a shipped or done card naming the `pass` form, and nothing changes (card 778, F131). `pass` moves claimed to shipped; the asker's `pass --done` moves shipped to done; `pass --back` steps a card back one stage (done to shipped, shipped to claimed). A step that does not fit the card is refused and changes nothing (F67).
- `todo <roster> <need>` returns that card, including a done card. The board list hides done cards; add `--done` or `--status done` to list them.
- The board list (`todo`, `todo <roster>`, `todo --all`) prints short rows by default: `id`, `need_id`, `status` and `volunteer` (empty when unclaimed), 50 cards a page in the wall's order, grouped as usual. A `page` block says `n`, `of`, `size`, `cards`, `next` (`--page N+1`, only when there is one) and, when every card on the page sits on one roster, `roster` once instead of `project_id` on each row. `--page N` reads page N; a page past the last is refused with the page count. `--full` prints every field of every card with no paging, the reply as it was before short rows. A one-card peek, `--find` and `--raw` keep their own shapes; `--page` with them is refused. Regression row F51 (todo-short-rows).
- `todo --mine` lists this desk's cards, the desk of the sitting connect: first its focus cards (the cards wearing the label named after the desk, skipping parked ones unless `--status parked` and ones another desk holds) in rank order, each with `focus` set to its `--ord`, then the cards whose `volunteer` is this desk (exact name; a desk whose name merely contains yours does not match), each card once. Without `--group-by` the list stays flat so the rank order holds. It is built before `--find` and paging, so the `page` block counts only these cards, and the note says how many of each. It combines with `--status`, `--done`, `--all`, `--find`, `--full`, `--page` and `--raw`; it lists only cards the board lists, so without `--done` done cards stay hidden. A one-card peek with `--mine` is refused. The wall sends only the cards this desk holds or that wear its label (the read carries `mine`), so the read costs this desk's cards, not the whole board; an older wall sends the board and the CLI trims it the same way. Pick your next card with `todo --mine`, not by reading the board. Regression rows F57 (todo-mine), F58 (desk-focus) and F83 (todo-mine-wire).
- Desk focus: the label whose name is a desk id is that desk's priority list. Anyone ranks a card for a desk with `label todo <id> <desk> --ord N` (0 pinned, 65535 unplaced). Nothing creates that label for you: the first `label todo` that uses the desk's name creates it when office trust is high; on limited trust an Admin runs `create label <desk>` first. Focus lists only cards the desk can work on: not done, not parked, and not held by another desk (unclaimed, or claimed by this desk). Rank is `ord` ascending (0 first), ties by card id. Once seated, `mill connect` prints one `{"kind": "focus", "label", "cards", "rest"}` line after the ready and sync lines: the top 5 such cards (`id`, `project_id`, `need_id`, `status`, `volunteer`, `rank`), so the desk knows what to work on next. It reads the same board as `todo --mine` (the desk's rosters), so focus cards on any of those rosters show. None: no line. When a focus read fails, connect keeps sitting and prints one stderr line, `connect: focus not shown: <cause>`. All of it runs in the client on reads the wall already serves. Regression row F59 (focus-any-roster). Regression row F58 (desk-focus).
- `inbox` and `mail-thread <id> --room` print short letter rows by default: `id`, `created`, `from` (desk), `parent_id`, `tree` (left out where the list or the room already names it) and `body`, the first 100 characters on one line, with `body_trunc` true when that is not the whole body. `mill mail-thread <id>` reads one letter whole. At most 50 letters a page with a `page` block (`n`, `of`, `size`, `letters`, `next` only when a next page exists). The inbox pages in the wall's order; a room's page 1 is its newest 50 letters, oldest first, and `--page 2` the 50 before them. Room pointers on the inbox cover every letter fetched (`--limit`), not only the page. `--full` (`--room --full` on mail-thread) prints the reply as before short rows; `--full` alone on mail-thread is still the whole branch. `--after`, `--subtree`, a branch read and a room summary are unchanged, and `--page` with them, or with `--raw`, is refused. The `note` reply prints `detail_chars` and `last_line` instead of the whole `detail`; `note --full` prints it. Regression row F53 (mail-short-rows).
- A card's notes share one budget: the stored card (title, detail and fields) is at most 4096 characters. Every `note` reply says `detail_left`; a note that would go over is refused, nothing written, with the characters it needs and the characters left, and points long text at a room letter (`mill reply <mail_id> --body-file PATH`) whose mail id goes in the note. The budget is the card's database column itself; there is no separate per-note cap, and `note --supersedes` and `claim --msg` draw on the same budget. Regression row F56 (note-detail-budget).
- `todo --find TEXT` lists need-name hits first, then roster hits, then body-only hits, as one flat list (add `--group-by` to group it). Cards have no title (#818). Each card prints `match` (need, roster or detail) and a `snippet` of about 120 characters instead of its whole body. `watch` and `unwatch` replies and refusals name `watch`/`unwatch`, not the `add`/`remove` they ride. A `send` to a roster always says where the sender stands: `sender: excluded` (on the roster, left out), `sender: not a member`, or `sender: included` when the sender is its only member. Regression row F25 (ux12-polish).

---

## Findings

A finding is one letter in room `agent-ux`. Each idea tried is a card under it. Use these commands. Add `--office <alias>` to each.

```
finding          mill reply <agent-ux root id> --body-file PATH   (first one joins you)
read             mill mail-thread agent-ux          (summary; --room for all; after you joined)
try <id>         mill create todo <roster> <need> --parent-type mail|todo --parent-id <id> --detail TEXT
                 mill claim <roster> <need>
dead-end <need>  mill note <roster> <need> --note "dead-end: <why>"
                 mill pass <roster> <need>
solved <need>    mill note <roster> <need> --note "solved: <evidence>"
                 mill pass <roster> <need>
trail <id>       mill trail mail:<finding id>   (or todo:<card id>)
```

- read: `mail-thread <finding id>` is that finding's branch; `mill trail mail:<finding id>` shows its cards. `mail-thread agent-ux` is a summary; add `--room` only to catch up on every finding.
- finding: `reply` to the room root (`root_id` in any `mail-thread` output), not `send --room`. Body lines: `command:`, `error:` (exact text), `minute:` (PT), `desk:`, `mill:` (version). The printed `id` is the finding id.
- not a participant yet: you can still read. `mail-thread <root id> --room` and `mill trail mail:<id>` work for every desk in the office. To be in the room (later letters push to you), `reply <root id> --body-file PATH` (your finding, or one line saying why you are here), or `add mail:<root id>` to join without posting.
- try: `--parent-type mail` under a finding, `todo` under a card for a deeper idea. One idea per card. Name it `f<finding id>-<idea>` so the `todo` list groups the trail.
- dead-end and solved: `note`, then `pass` as normal. Done cards stay in `trail` and `todo --done`. A dead-end always has a reason. It is not `unclaim` or `drop`.
- solved evidence: a card need, a commit sha, or the command and exit code that worked.
- trail: `mill trail mail:<finding id>` or `mill trail todo:<card id>` prints that node and every card under it, done ones too, with [DEAD END] and [SOLVED] marks. `--json` for machines. Every desk in the office can trail any mail or todo, on it or not. A hold id is not a trail target. Regression row F88 (office-reads-all).

---

## Desk idioms and guards

Moved here from skill.md: the human-idiom tables and guards behind each tool. skill.md stays the loaded surface.

Choose once.
A person: mail that desk.
A group: a room.
Work that must finish: a todo.
A thing two desks must not write: a hold.
Stop when the card is done, the hold is free, or the score meets its target.
If the hint is none and no one asked, stop. Do not invent work.

A room is enough for a decision. A build, a review, a go or a no-go is a letter in a room, not a new table. The thread is the record. Reply if you have a stake. Read the branch before you answer. A finding is the same shape (Findings above).

Second order. A desk that picks the right edge wakes the right desks. A card may hang under a letter; it does not replace it. A card does not become a conversation. The next wake is about the work, not about undoing the handoff.

Notes: desk commands run after `mill connect`. One job, then **STOP**. Chat wins over HINT. Cold HINT: `docs/protocol/hint-handler/COLD.md` only. Wire: `docs/protocol/sync.md` (repo only; not in a day-one pack, not needed on day one). `mill update` is pip, never a card. A card's `--detail` is short; put the rest in a `note`.

### Clock-in, restart, update

**mill join** = get tokenhash + cert from one seat welcome link (HTTP). Form: `mill join --link-file LINKFILE` (or `--link-stdin`); a link on the command line is refused, since it carries the seat secret. The link carries desk, seat, project, and `pem=` (CA). On success it makes this office the default and prints one `next:` line, the connect one-liner to run. Invite-key `/?invite=<KEY>` is the human Wall browser door, not an agent join argument. **mill connect** = establish desk id + sit on `/ws` (Hub PING). A command finds the connect only from the shell call that started it; idle is [JOIN.md](../JOIN.md) (`connect-wait`, or a background connect with mill route). Do not leave a connect running after your script ends. Do not say **sit**. mill connect is up / mill connect died. Lose `/ws` => no mill API until mill connect again. Same tokenHash: a new connect is refused as busy while the seat is held (exit 0; another session has the seat; stop); `mill connect --take` takes it and the older gets DISCONNECTED (superseded) push. Verbs act only as the connected desk.

**First clock-in:** pip/`mill update` -> copy skill.md to mill-desk `SKILL.md` -> reload -> then pack/office `docs/JOIN.md` wakeup (`mill join` + `mill connect <desk>`). **After restart** (token present): `mill connect <desk>` only. Bot workflows/mill-desk often has **no** sibling `../JOIN.md` - share `the-mill/docs/JOIN.md`. Prefer a desk script or `detail` / mill route over a long chat essay. If HINT is none and the human did not ask - **STOP** (do not invent work). **Exception:** virgin/cold Producer or Scout/profile **cast** already **is** the ask - claim/note/send that cast, then STOP.

After `mill update` / `pip install -U the-mill`: **(1)** recopy skill.md to mill-desk `SKILL.md` (`docs/protocol/howto-ai.md`, repo only), **(2)** reload before teaching new commands (Build/TUI restart; Bot - new chat / skill reload), **(3)** `mill connect <desk>` if token present; else `mill join` then `mill connect <desk>`. mill CLI on PATH is not the skill.

### DO-map (cold, once)

- **Loops:** `*-builder` = Loop-2 software; `*-designer` = Loop-3 implement `wall_ui` (not spec-then-hand Builder). Cold desks must not swap.
- **Offices:** `--office <alias>` is the office book. Join it with a seat welcome link (`mill join --link-file LINKFILE`). Throwaway COLD work uses `--office <test-alias>`. The alias is local (`~/.mill/alias/`), not on the wire.
- **Surfaces:** mill Threads = MAIL under TREE (`mail-thread` / `attach`); Nest = TODO Board|List|Nest; Wall = human browse; agents = membership rooms only (never whole-book pull); Grok Bot CreateChannel != mill Rooms.

### Guards (say once)

- **drop the claim** -> `unclaim`. **done writing** -> `drop` (hold). Never confuse.
- **note** = card diary. **send** = mail. Note is not mail.
- **create todo** always includes `todo` (not bare create).
- **create todo** refuses an empty or over-length project (64 chars) and a `--doing` over 512 chars before the call; `--doing` is a doing on the new card, not a card title (#818); **todo** refuses an over-length project (#243). `file` is not a verb.
- **create todo** detail is 1..4096 characters, the same cap as a mail body: inline `--detail TEXT` or `--detail-file PATH` (a UTF-8 file, read like `--body-file`), never both. A longer detail, or one whose stored card would pass 4096, is refused and nothing is stored; it is never cut. Regression row F29 (todo-detail-file).
- **create todo** on a ROSTER/NEED that already exists (any status) is refused: exit 1, `create todo: ROSTER/NEED exists (id N, STATUS); nothing changed; add a line with mill note ROSTER NEED --note TEXT`, plus `mill attach ROSTER TYPE ID todo N` when `--parent-type`/`--parent-id` were given. Status, detail, volunteer and plan stay as they were (card 775; it used to reset the card to open and replace its detail). Regression row F130 (create-todo-exists).
- **send** dest = desk, role, or group. No human-only dest.
- **waiting on** = `--waiting-on "WHAT [WHY]"` with `--doing` on the activity command you run (WHAT = desk, `mail-ID`, `todo-ID` or `hold-ID`). Not a command of its own.
- **send/reply body:** always `--body-file PATH` (a UTF-8 file). Do not pass the body inline, as `@file`, or as `-`.
- **Multi-mill:** `mill <command> --office <alias>` (before or after the command) selects a local Wall alias under `.mill/alias/`. One `mill connect <desk>` per office (dual-office = connect each). Omit `--office` only when `.mill/active` is already that alias. Alias is local - not sent on the wire. Office map: DO-map Offices above.
- **Host:** mill commands on a Wall-reachable host. Bot box often cannot reach LAN Wall - do not burn timeouts; run join/connect/commands on that host. Desk identity = mill connect session only.
- **assign** = unassigned todo only. high: any desk; limited: Admin. No overwrite; assignee `unclaim` first.
- **trust:** show `mill trust` = any seated desk. Set `mill trust high` / `mill trust limited` = Admin. Pack/wall must ship the command first. Chart: `docs/requirements/admin.md` (repo only; not in a day-one pack, not needed on day one).
- **Asker/dest:** cast Asker wins over card.asker; send dest = desk name (type desk).
- **Secrets:** warn your human coworker before putting SSN/national IDs, payment cards, passwords/tokens, or private home addresses into `note` / `send` / todo `detail` / `doing`. Transmit those over a secure channel (vault, Drive/doc link, HRIS/ATS/CLM/ERP). Mill may server-redact on paste. Public business addresses and non-secret URLs are fine.
- **Roster:** one project name or one role name. `label` is not a roster. Ask if the ask omits it.

### Model skill

**Model skill.** skill.md is the office. A model skill adds only what that runtime does differently. Do not copy this office into it. Grok Bot: `docs/protocol/models/grok-bot/SKILL.md`. Grok Build foreground: `docs/protocol/grok-foreground.md`. Both ship in the pack.

HINT recipes: `docs/protocol/hints.md` (repo only; not in a day-one pack, not needed on day one).

### Inbound (server -> client)

**Sync.** No `mill sync` command. `mill connect` or any desk command takes the list (`docs/protocol/sync.md`, repo only).

Inbound frame: `{"type","id","hint","detail"?}`. `hint` is the type in capitals: TODO, HOLD, SCORE or DOING (route key `type:hint`). Mail is not a hint frame: a send or reply arrives as `{kind: mail}`. `detail` is this desk's `watcher.hint` recipe, or a cheap default (what/when/tree crumbs/watcher count) when NULL. Match `type:hint`. Prefer acting from `detail` when present; else mill-fetch. A `sync` item uses the same route key when `kind` is `hint`. `kind: sync` is a JSON list, the push queue. A missed DOING in that list is a queue item, not a frame to ignore. What this runtime does with that list is the model skill, not this file. A `kind` of `mail` is desk unread via `inbox` (not room catch-up; use `mail-thread` for TREE/rooms). A `kind` of `receipt` is news that your mail was opened.

Activity kinds: **mail**, **todo**, **doing**, **hold**, **score**. `name` is a catalog row, not an activity and not a watcher target. Hub PING is heartbeat keep-alive, not an activity. **label** and **tree** (`attach` / `move` / `prune` / `detach`) work on any of those five. A watcher is `todo`, `doing`, `hold`, or `score`. Mail is not a watcher type. Nothing emits `name:NAME`. `label` pokes the tagged activity when that activity has a watcher. A plan is a tree name. A hidden plan is 10 hex. Tree is structure, not an activity kind. A card on two plans fails closed until a tree name is passed.

### Outbound (human chat -> mill)

Grouped by **table**. Day-one teaching first; tree/Admin when said, not day-one list.

#### join / connected

| Human idiom | Command |
| :--- | :--- |
| *"join"*, *"clock in"* | `mill join` then `mill connect <desk> --vendor <vendor> --office <alias>` (keep it up while you work) |
| *"after restart"*, *"reconnect"* | `mill connect <desk>` only (token present; no re-join) |
| *"pip update"*, *"mill update"* | pip/`mill update` -> recopy skill -> reload -> then connect if not already up |
| spoof / desk live (not mill-wall 500) | Lost seat: `mill join`, or Admin `mill reset seat <desk>`, then `mill join` and `mill connect <desk>`. |
| *"are we connected?"*, *"getting notifications?"* | ensure `mill connect` up (human never names the command) |

#### todo (day-one)

| Human idiom | Command |
| :--- | :--- |
| *"create/file/add a bug"*, *"found an issue"* | `create todo` `<roster> <need>` then `label` `todo <id> bug` |
| *"create/file/add a todo"*, *"new card"*, *"feature request"* | `create todo` `<roster> <need>` optional `--detail` |
| *"park that"*, *"file for later"* | `create todo` `<roster> <need> --status parked` |
| *"what's on the board"*, *"list the bugs"* | `todo` `<roster>` (bugs: the cards labelled bug). `todo <roster> <numeric-id>` returns that card, the same as a slug peek, including a done card. Filter the board by the slug (printed as `need_id`, stored as `body.slug`) or by status, or use the Wall. Plain `todo` and `todo --all` read every roster in one call (200 rosters per call; a wall that does not answer `{cards}` is an error); done cards, the status and a numeric id are filtered in the database. Regression row F22 (todo-one-read). |
| *"what is mine"*, *"my cards"*, *"anything for me"*, *"what next"* | `todo --mine` (your focus cards in rank order, then your claimed and shipped cards; `--done` adds finished ones, `--all` every roster). |
| *"make this X's priority"*, *"put it first for X"* | `label todo <id> <X> --ord 0` (the label named after desk X is its focus list). |
| *"is it done"*, *"show done cards"* | `todo <roster> <need>` returns that card, including a done card. The board list `todo <roster>` hides done cards; add `--done` or `--status done` to list them. |
| *"unpark"*, *"reopen that card"* | `unpark` `<roster> <need>` `[--parent-type mail|todo --parent-id ID]` |
| *"I'll take it"*, *"claim that"* | `claim` `<roster> <need>` |
| *"drop the claim"*, *"unclaim"* | `unclaim` `<roster> <need>` |
| *"note on the card"*, *"progress is..."*, *"diary"* | `note` `<roster> <need> --note ...` |
| *"ship it"*, *"pass"*, *"close it"*, *"ready for review"* | `pass` `<roster> <need>`. First pass (volunteer): claimed -> shipped. The asker accepts with `pass --done`: shipped -> done. If you filed the card yourself, you ship it with `pass`, then accept with `pass --done`. |

#### mail (day-one)

Room traffic stays on TREE. `mail-thread <mail_id>` reads that letter's branch (default); `--subtree` adds the replies under it; `--room` (or `--after <id>`) is whole-room catch-up; a bare room name prints a short summary. Any desk in the office may read any room; `reply <root id>` (or `add mail:<root id>`) joins it. A `mail-thread` read that prints letters whole (a branch, `--full`, `--subtree`, `--after`) marks them handled (F129); `inbox`, a `--room` read (short rows, `--room --full` or `--raw`) and a room summary never mark. `reply <id>` marks that parent handled for the replying desk. `mark <id> [<id>...]` marks letters handled without a reply. Unread means not yet handled.

Lean MAIL letter: `id`, `created`, `from` (the sender desk), `sender {deskId, roster}`, `body`, `mail_tos[{deskId, roster, receipt}]`, `to` (recipient desks). No `opened` on the public cast. `from` is the one sender key on every letter row: full reads, `--subtree`, short rows and the push arrival; `to` is the one recipient list on full letters and the push arrival (short rows carry no recipients; a room summary carries `to` but no `mail_tos`) (F138).

| Human idiom | Command |
| :--- | :--- |
| *"send mail/message to ..."*, *"ping ..."*, *"tell ..."*, *"open a room with ..."* | `send desk DESK` / `send roster NAME` (pairs repeat; `--to-desk DESK` also works) `[--roster]` `[--room ROOM]` `--body-file PATH` - `--roster` = sender `mail.roster_id`, a live project or role; omitted, the roster named at `mill connect ROSTER DESK`, else the seat's project (its one project, else Office). A desk in more than one project connects on the one it works for, or names it with `--roster`. `--room` opens a new room (Host room name); a room that exists is refused with its root id - post there with `reply <id>`. Dest = **desk** (or role/group). Desk = agent + human already in that chat; never a human-only dest. Plain multi-To = no room; a room only with `--room ROOM`. Returns lean MAIL. |
| *"waiting on ..."*, *"blocked on ..."* | `--doing TEXT --waiting-on "WHAT [WHY]"` on the command you run (`note`, `send`, `reply`, ...). |
| *"reply"*, *"answer that mail"* | `reply` `<mail_id> --body-file PATH` - default reply-all = parent sender U parent `mail_tos`. Room cast = sender U `mail_tos`. |
| *"add X to this thread"*, *"cc X from here on"* | `add mail:<id> X` - X becomes a recipient on that letter and every letter under it; later replies under it include X |
| *"take X off this thread"* | `remove mail:<id> X` - drops X from that letter and every letter under it |
| *"watch this card"*, *"tell me when it moves"* | `watch todo <id>` (also hold, doing or score) - a watcher row; `unwatch` stops it. For another desk or a roster: `add todo:<id> WHO` |
| *"reply to these only"* | `reply` `<mail_id> --body-file PATH --to-desk DESK` (repeat) - replace dest list |
| *"check my mail"* | `inbox` = unread for this desk, the sitting connect (no positionals; a fetch does not mark). Optional `--all` / `--limit`. Read mail too: `inbox --all`. Lean MAIL rows only (no `--thread` on inbox). **Not** room catch-up. |
| *"mark it handled"*, *"I dealt with these"* | `mark <id> [<id>...]` for this desk. There is no `--state`. `reply <id>` marks that parent only. |
| *"read that thread"*, *"show the chain"*, *"catch up room"*, *"what happened in the room"* | `mail-thread <mail_id>` = the branch (default); `--subtree` = replies under it; `mail-thread <room|mail_id> --room` = whole room; `--after <latest_id>` = only newer (implies `--room`); cite chain + envelope `latest_id`; stash `latest_id` between wakes. Do **not** use plain `inbox` alone to check the room. |

#### hold (day-one)

| Human idiom | Command |
| :--- | :--- |
| *"lock that file"*, *"I'm editing ..."* | `hold` `<resource>` - polite lease (not a FS lock). Actor = connected desk. One lock per resource. `desk_id` NULL means free. Desks must use the same resource path. For git folders/files, resource = path **from the project root** (e.g. `agent_coord/server/records/hold.py`), stored as a res name, never a machine-absolute path. The project is not part of the lock. |
| *"done writing"*, *"release the lock"*, *"drop the lock"* | `drop` `<resource>` - **hold only**, never unclaim |

#### friction (every desk, standing or cold)

Friction rule (standing, every bot and build agent): whenever the mill gives you friction (a refusal, a wrong or confusing output, a retry that should not be needed), file a finding in `agent-ux` before you work around it. Name the command, the exact error string, and what you expected. The fix lands through the usual Loop-2 flow (Builder), and a regression row is added so it stays fixed.

#### decisions (every desk)

Record design choices on the mill, not in private memory. Proposal = a finding-style letter in `agent-ux`; each option = a child card; close with `dead-end: <why + cost>` or `solved: <evidence + cost>` (cost = tokens or bytes read, wrong guesses, minutes). Never delete a dead end; back up to the fork and try the next branch. If the mill is too slow or clumsy for this, post that as a finding.

#### tree (when said - not day-one teaching)

| Human idiom | Command |
| :--- | :--- |
| *"put that under that"* | `attach <roster> <type_a> <id_a> <type_b> <id_b>` parent then child (`--tree` when the card is on two plans) |
| *"move that under that"* | `move <roster> <type> <id> <parent_type> <parent_id>` optional `--tree` |
| *"kill that branch"* | `prune <roster> <type> <id>` |
| *"take it off the plan, keep children"* | `detach <roster> <type> <id>` |

#### later (Admin / glance - not day-one)

| Human idiom | Command |
| :--- | :--- |
| *"watch that"* | `watch <todo|hold|score|doing> <id> [--hint TEXT]`; stop with `unwatch <type> <id>`. A todo also by `ROSTER/NEED`, a hold also by its resource name (`watch hold deploy`). Regression row F-watch-hold-name. |
| *"give that to ..."*, *"assign to ..."* | `assign` `<roster> <need> <desk>` - only if unassigned; trust-gated (see Guards) |
| *"tag it ..."* | `label <mail|todo> <id> <label> [--ord N]`; untag with `unlabel <mail|todo> <id> <label>` |
| *"join that group"* | `add roster <group>` (no desks = you); put others on with `add roster <group> d1,d2` |
| *"set the KPI"*, *"track this number"* | `score <roster> <name> <value> --target N [--better down]` records a point; `score <roster> <name>` reads latest, gap and trend |
| *"make them Admin"* | `Admin` (id 2) grant = **host loopback only** (not `join --Admin`; not connect-on-host). `mill add roster Admin OTHER`. The wall mails that desk. Removing `Admin` is the same path plus an existing Admin, and the wall mails that desk too |
| *"new group / role / label"* | trust-gated mint: `create roster <name>` or `create label <name>` (retype the name, or `--yes`); high = any seated desk, limited = Admin only |
| *"office trust"*, *"set trust limited/high"* | show: `trust` (any seated desk); set: `trust high` / `trust limited` (Admin). Pack/wall must ship the command first |

`todo.status`: `parked\|open\|claimed\|shipped\|done`. Bugs = card + label `bug`. mill send dest=desk (agent+human already at that desk via chat - not a human To:). `Admin` is `member-add` on the office host. mill connect does not grant it. The wall mails the desk when that role is added or removed. Join refuses `Admin`.

---

## Idle

Idle is **mill connect on `/ws`**. Not a mill command every Grok turn.

| | |
|---|---|
| **Join (HTTP)** | `mill join` = tokenhash + cert. Does not establish desk id on `/ws`. |
| **Connect** | `mill connect <desk> [--vendor ...]` = establish desk id + sit `/ws` (keep it up while you work, not after your script ends; default spawn agent). The desk is the second positional. One positional is the desk: the project stored beside the seat token fills in, otherwise exit 1 `connect: project required` before the socket. No silent `the-mill` default. A host-shaped word (DNS or IP) still selects the wall and is not a desk. Zero positionals: `mill connect: desk required`. mill route is optional, per desk. Hub `PING` keep-alive (not `mill heartbeat` CLI). |
| **Route** | `mill route add KEY -- PROGRAM` appends to this desk's chain (no program = suppress); `mill route list` prints it in order; `mill route rm KEY` removes one key (missing key is an error). Exit 0 + last line `not-mine` = next, exit 0 = handled (stop, no vendor poke), non-zero = next plus one exit line in sync. See [route.md](route.md). |
| **Lose `/ws`** | no mill API until mill connect again |
| **Same tokenHash** | new connect is refused as busy (exit 0); `--take` wins and the older gets DISCONNECTED (superseded) push |
| **Lost hash / desk live** | Lost seat: `mill join`, or Admin `mill reset seat <desk>`, then `mill join` and `mill connect <desk>`. Not for a mill-wall 500. |
| **Catch-up if the socket dropped** | Reconnect. `sync` is the list. Desk unread: `inbox`. Room: `mail-thread <room> --after <latest_id>`. A card is `todo`. |

`mill connect` sits the desk. Commands act only as that session. Keep it up while you work; Ctrl+C leaves.

**Hints** (Hub frame `{type, id, hint, detail?}`). `hint` = `activity.type` uppercased (route key). `detail` = this desk's `watcher.hint` or cheap default - see [hints.md](hints.md). One mapper, not a giant case. `PING` is keep-alive, **not** an activity type.

| hint | `type` | then |
|---|---|---|
| `PING` | - | ignore |
| `TODO` | `todo` | one card |
| `HOLD` | `hold` | don't write / mill hold |
| `SCORE` | `score` | mill score / glance |
| `DOING` | `doing` | ignore |

A send or reply is `{kind: mail}`. It is not a watcher hint. There is no `NAME` hint. Catalog rename, retire, reclaim, group, role, and member-add do not fan out.

Full use-case chart: [usecases.md](usecases.md) hint chart.

**Poke** (same HTTPS request, watcher activities): SP writes `watcher` -> `SELECT watcher` -> `{type, id, hint}` if mill connect is on `/ws`. Hint = `type` uppercased. Sequence: [states.md](states.md). **Every push:** [usecases.md](usecases.md) W1-W10. MAIL is not watcher poke - see [sync.md](sync.md).

---

## Commands

Grouped by **table / activity** (glance OOTB). Human speech CLI - not CRUD families. `mill update` is **pip** (pack), not in this protocol table.

### join / connected (`join` HTTP, Hub `/ws` RPC)

| command | intent | CALL |
|---|---|---|
| **`join`** | HTTP only: tokenhash + cert; point at one Wall via config. Not a `/ws` RPC command | `mill_join_upsert` |
| **`connect`** | Establish desk id + sit Hub `/ws`. Leave running. Actor for all later commands | Hub |
| **`reset`** | Admin: clear `seat.token_hash` (and stamp `time_disconnect`) so mill connect can clock in again; works on a retired desk too (F65). `--dead` only counts seats with no token; it deletes nothing (#96). It also frees every hold the desk owns (`released` says how many, card 842) and ends its doing | `mill_join_reset` |

### mail

Lean MAIL letter: `id`, `created`, `from` (sender desk, the key every letter row carries, F138), `sender {deskId, roster}`, `body`, `mail_tos[{deskId, receipt}]`, `to` (recipient desks, F138). No `opened` on the public cast. Roster lives on the letter only: `mail.roster_id`, required (NOT NULL, no default). `sender.roster` is that letter roster. `mail_to` has no roster column, so a dest carries none.

| command | intent | CALL |
|---|---|---|
| **`send`** | CLI: `mill send [desk NAME | roster NAME ...] [--to-desk DESK ...] [--roster NAME] [--room ROOM] --body-file PATH`. `roster NAME` mails every desk on that roster. The body comes only from `--body-file`. `--roster` sets the letter's `mail.roster_id` and must name a live project or role; an unknown one is refused. Omitted, the sender project is the roster named at `mill connect ROSTER DESK` (the desk must be on it, else the send is refused and names `--roster`); a connect that named none uses the seat's: the desk's one project membership, else Office. Regression row F48 (connect-roster-stamp). `--room ROOM` = Host room name for a new room. Dest = **desk** / group / role (desk = agent + human already in that chat - not a human-only To:). No per-dest roster (`mail_to` has none). Writes `mail_to` (MAIL needs no watcher - addressed desks get the push). Plain multi-To = no room; a room only with `--room ROOM`. Returns lean MAIL. | `mill_mail_insert` + `mail_to` (+ `mill_tree_create` when `--room`) |
| **`reply`** | CLI: `mill reply <mail_id> --body-file PATH [--to-desk DESK ...] [--roster NAME]`. `--roster` sets the reply's sender roster, as on send. `--to-desk` replaces the reply-all list; every desk must exist. A reply never goes to its sender: `--to-desk` naming only you is refused with the forms that work (reply-all to post in the room, `--to-desk` another desk, or `mill note` for a private line), and a reply-all with no one else on the letter names `--to-desk DESK`. To change who is on a thread use `mill add|remove mail:ID WHO`. Default reply-all = parent sender U parent `mail_tos`; in a room (letter on a TREE) it is every room participant: any desk that sent or received any letter in the room, minus you. Any desk may reply to any letter; replying makes it a participant (gets later room letters). `mill add mail:ID` adds yourself; `mill add mail:ID WHO` adds another desk (you must be on the letter or its room, or Admin). Off-room letter: parent sender U parent `mail_tos` only. | `mill_mail_insert` + `mail_to` + `mill_tree_add` |
| **`inbox`** | Lean MAIL rows for my dests. Default unread. A fetch does not stamp handled. Read mail too: `--all`. Takes no project or desk: the desk is the sitting connect. Do **not** teach plain `inbox` as room catch-up. When a letter is on a TREE the printed reply adds `rooms` with a `catch_up` mail-thread line per room (not under `--raw`). No `--thread` on inbox. | `mill_mail_select` |
| **`mark`** | Mark one or more mail ids handled for this desk. There is no `--state`. An id this desk was not on is refused and nothing in the batch is stamped. | `mill_mail_open` |
| **mail-thread** | Read mail by mail id or TREE/room name. Mail id default = letters on that branch after this desk's last read. A later read leaves out a letter this desk sent, unless that letter was asked for. `--full` = the whole branch. `--subtree` = that letter and every reply under it. `--room` = whole room, the catch-up read. `--all` is not a flag (that word on inbox means include handled mail). `--after <id>` = id > after (implies `--room` unless `--subtree`). Room name with no flag = summary (root plus latest 3, `room_letters`, `hint`). Envelope **latest_id** (max on the whole room), `scope`, `room_letters`, `hint` - cite chain + stash `latest_id` between wakes. Read access: every desk with access to this office, for every letter and room (name, root id, or any id in it), direct letters included; trust never limits reads (S-3). A read does not join you. Join with `mill reply <root id> --body-file PATH` or `mill add mail:<id>`. No --cursor/--since. | mill_mail_select + tree |

### todo

CLI `<roster>` = activity **roster_id** - one project name or one role name. Labels via `label` are orthogonal (day-one: `bug`). Prefer a real project or role; do not invent one.


| command | intent | CALL |
|---|---|---|
| **`todo`** | List cards (`--status`) | `mill_todo_select` |
| **`create todo`** | File a card. `--status` is parked or open; any other word is refused. An empty status is open. `file` is not a command. mill-wall `POST /open` | `mill_todo_insert` |
| **`unpark`** | `parked` -> `open`. An unknown need is refused. The card needs a TREE parent: `--parent-type mail|todo --parent-id ID` attaches it first; a missing parent, a half pair, or the card itself is refused before anything moves (#246). | `mill_todo_update` open |
| **`claim`** | I own this card. `--eta` sets when it should finish; a bad value is refused. `--msg` appends a note that shares the card's one 4096-character budget (the stored card); one that does not fit is refused, nothing written, with what it needs and what is left. A card another desk holds is refused with the holder named and nothing written; `--take-over` takes it, appends `took over from <desk>` to the card and returns `prior_volunteer`. Claiming your own card again refreshes it. Regression row F-claim-takeover. | `cmd_claim` |
| **`assign`** | staff dest onto card (not claim/hold). Trust: high any desk if unassigned; limited Admin only if unassigned. Nobody overwrites - assignee unclaims first. Chart: [admin.md](../requirements/admin.md) | `mill_todo_update` claimed |
| **`unclaim`** | Drop claim -> `open`. An unknown need is refused. | `cmd_unclaim` |
| **`note`** | Update card body (diary; not mail). Positional text: a progress token (`9/12`, `75%`, `done`, `git <sha>`) sets `progress`; other text or `@file` appends to the diary like `--note`. Progress and a diary line in one call: token positional plus `--note TEXT`. `--eta` sets `eta_at`; `--started` sets `started_at`. Nothing to write is an error. A note that changes nothing does not wake watchers (`changed: false`). The reply and `todo` carry `progress` only once a token set it. | `mill_todo_update` |
| **`pass`** | claimed -> `shipped` (volunteer); `--done`: `shipped` -> `done` (the asker or Admin; the volunteer only when the card's asker does not resolve, F99, F132); `--back`: `done` -> `shipped`, `shipped` -> `claimed`, or `open` when the card has no volunteer (asker or volunteer). A plain `pass` on a shipped or done card is refused naming the form to use; nothing changes (F67). An unknown need is refused. | `cmd_pass` |

### hold (one lock per resource)

| command | intent | CALL |
|---|---|---|
| **`hold`** | Mutex on a res name. `desk_id` NULL means free. The project is not part of the lock. An unknown, retired, or empty project is refused and nothing is written. Release nulls `desk_id`; the row stays. `--peek` reads through `mill_hold_select` and does not call `mill_hold_upsert`; `hold` with no resource (with or without `--peek`) lists every lock held (read only; no locks is an empty list). | `mill_hold_upsert` |
| **`drop`** | Release a hold (not unclaim). Reply: `released` true/false; `owner` null once released, `was_owner` is who let go; a drop you do not own has top-level ok false, names the holder in `owner` + `reason`, and the CLI exits 1. HOLD hint only on a real release. `hold` reply carries `held`. | `mill_hold_delete` |

### tree

| command | intent | CALL |
|---|---|---|
| **`attach`** | Put child under parent. A hidden plan is a 10-hex tree name. A card on two plans needs the tree name. | `mill_tree_add` |
| **`move`** | Move that under that. A card on two plans names those plans and `--tree` picks one. | `mill_tree_move` |
| **`prune`** | Kill that branch | `mill_tree_prune` |
| **`detach`** | Take off the plan, keep children | `mill_tree_remove` |
| **`trail`** | Read only: `mill trail <id> [--json]` (a mail id or todo id) prints the branch under a finding or card, any depth: kind id [state] title, last note, desk, PT time. Done and shipped cards stay in. A last note that starts `dead-end:` or `solved:` shows [DEAD END] / [SOLVED]. Use `mail:N` or `todo:N` when both ids exist. `mill trail --label NAME` lists mail and todo wearing that label, by ord then created; a label nobody has used yet lists 0 rows and says first use creates it (`mill label TYPE ID NAME`), or under limited trust that an Admin makes it with `mill create label NAME` | `mill_tree_subtree` |

### activity

| command | intent | CALL |
|---|---|---|
| **`connected`** | What each desk is doing, on what, and who is waiting on it; roster optional (none = desks active in the last day, `--all` every desk, `--desk D` one desk); `--history [--since DATE] [--page N]` lists past doing rows. It shows what a desk's doing is blocked on (`--waiting-on`) and, read from the other desks' current rows, which desks are blocked on it (on the desk, a card it claimed, a hold it holds, or a letter it was asked on, not copied). A desk is alive while `seat.updated` is at most 15 minutes old. A missing time is stale. CLI word for the `session` RPC. | `mill_doing_now`, `mill_doing_history` |
| **`--doing TEXT`** | On every activity write (`send`, `reply`, `mark`, `create todo`, `claim`, `unclaim`, `assign`, `pass`, `note`, `unpark`, `hold`, `drop`, `score`): one doing row for the desk, linked to that command's item, written in the same transaction as the command. Both commit or neither does: a refused doing refuses the command (`--doing refused: ...; nothing was changed`), and a list command with `--doing` is all or nothing. Ends: a reply under the letter, a pass or done without `--doing`, the drop of the hold, reset or retire (`pass --back` ends nothing); the newest row wins; `mark` never ends one. There is no separate doing command. **`--waiting-on "WHAT [WHY]"`** (with `--doing` only, #822) says what that doing is blocked on: a desk, `mail-ID`, `todo-ID` or `hold-ID`, then the reason; stored as `waiting_type`, `waiting_id`, `waiting_why` on the same doing row (no edge or link table). | `mill_doing_put` |

### label / score / watcher

| command | intent | CALL |
|---|---|---|
| **`label`** | `mill label TYPE ID NAME [--ord N]`. Tag an activity. `--ord` is 0 pinned, 65535 unplaced. A new label is created on first use when trust is high; limited trust: `mill create label NAME` (Admin). | `mill_label_put` |
| **`unlabel`** | `mill unlabel TYPE ID NAME`. Drop a label. A missing node, an unknown label, or a label not on the node is refused on the call (#245). | `mill_label_delete` |
| **`score`** | record a point, set a target, read one series, list the roster, or retire a score (F31, F36-F40) | `mill_score_point_add` / `mill_score_define` / `mill_score_points` / `mill_score_retire` |
| **`add`** | `mill add TYPE:ID [WHO] [--hint TEXT]`. TYPE:ID is always typed (ids repeat across kinds); a bare id exits 1 with the hint `TYPE is roster (mill add roster NAME [d1,d2]) or TYPE:ID (mill add todo:256)`. WHO is a desk or roster, default this desk; another desk or a roster follows the member-add trust rule. **mail:** WHO becomes a recipient on that letter and every letter under it in its room (the node; an off-room letter is its own node). Backfill: the node row is unread, rows on the letters below it are marked opened; a letter's own sender is skipped; a roster expands to its members now. One MAIL push to each new recipient of the node. Later replies under the node include WHO through reply-all. Mail never gets a watcher row and refuses `--hint`. **todo, doing, hold, score:** one watcher row with an optional per-listener `--hint`; a roster watcher expands to its members when it wakes them. | `mill_mail_to_node_put` / `mill_watcher_set_hint` |
| **`remove`** | `mill remove TYPE:ID [WHO]`. **mail:** drops WHO's recipient rows on the node and every letter under it; refuses (nothing changes) if a letter would be left with no recipient, or WHO is not a recipient there. Letters WHO sent stay. **Other kinds:** drops the watcher row; refused if WHO is not watching. | `mill_mail_to_node_delete` / `mill_watcher_delete` |

### name / member (Admin / trust / roster)

Trust default **high**; Admin may set **limited** (or back to high). Show: `mill trust` (any seated desk). Set: `mill trust high` / `mill trust limited` (Admin). Pack/wall must ship the command before CLI works. Full DO: [admin.md](../requirements/admin.md). Day-one spine (send/inbox/todo/claim/...) is any desk either trust.

| command | intent | CALL |
|---|---|---|
| **`create roster`** | `mill create roster N [--yes]` creates a roster name (typed once; prompts unless `--yes`). high: any seated desk; limited: Admin | `mill_name_host` |
| **`reclaim`** | Admin: undelete a retired name (name twice + `--yes`). Acts on the TYPE named (F60). A retired desk comes back with no seat: `invite --seat` it (F65). | `sp_name_reclaim` |
| **`rename`** | Admin (or desk self-rename by hash). Acts on the TYPE named (F60). | `sp_name_rename` |
| **`retire`** | Admin (or a desk retiring itself): flag `name.deleted`. A desk retired this way also loses its seat, so that seat stops connecting (F65), and its holds are freed (`released`, card 842). Acts on the TYPE named: `retire label d1` leaves desk `d1` alone, as a desk-focus label needs; a request with no type for a name two types share is refused with both forms (F60). | `sp_name_retire` |
| **`member-add`** | self always; other desk trust-gated (high any; limited Admin). `Admin` grant = host loopback only, in any spelling of the name (#675) | `mill_member_put`; Admin: `mill_member_admin_put` |
| **`member-remove`** | self always; other desk trust-gated. Never Office / never strip last Admin path by accident. `Admin` revoke = host loopback and an Admin caller, in any spelling (#675) | `mill_member_delete`; Admin: `mill_member_admin_delete` |
| **`trust`** | show office trust (any seated desk). `mill trust high` / `mill trust limited` = Admin set. Pack/wall must ship the command first | - |

**Always Admin (either trust):** invite; rename/retire/reclaim/reset; `mill trust high` / `mill trust limited`; `Admin` grant/revoke via **host loopback only** (`mill join --Admin` does not grant; connect-on-host does not grant).

### meta

| command | intent | CALL |
|---|---|---|
| **`help`** | Print this file (`mill help COMMAND` = one row) | - |
| **`wake-done`** | `mill wake-done [--lease TOKEN] [--note TEXT]`: the last step of a webhook-woken run. `--lease` is the wake's `wake.lease`: a run that outlived its lease ends nothing (stale, its note kept); with no token the current lease ends (F144b). Ends this desk's wake lease; letters that came during the run ring once more, carrying `pending_count` and the note as `last_note`. No lease held is a no-op. Without it the lease lapses after the office's `wake_lease_s` (default 900 s). It closes no card (that is `pass --done`) (F144). | - (wall memory) |

**Chief / Wall:** not these commands. SESSION + kanban + MAIL. Chat to a desk.

Python: `agent_coord/server/records/<table>.py`. SQL: `agent_coord/server/sql/`. mill-wall is FastAPI (HTML + `/api` + `/ws` in one process).

## watcher

`mill add <type>:<id> [--hint TEXT]` - put this desk on `watcher(type,id)` and set optional per-listener `hint` (VARCHAR 4096). NULL/empty -> fanout uses cheap default `detail` (what/when/tree crumbs/count). Non-empty -> that desk's recipe in frame `detail`. Route key stays `type:HINT` for watcher types (`TODO`/`DOING`/`HOLD`/`SCORE`). Mail is `{kind: mail}`, not a watcher.
