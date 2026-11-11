# Card 1125: activity_history protocol (draft)

Status: design draft by the auditor desk for card 1125 (activity_history / card-edit-replaces), targeted at 0.8.13. Nothing is built. The protocol was read against main e028bac (card 1113); the mail and todo edit and open writers are unchanged on main d783015 (0.8.12), which this change bases on. Check ids in `verify/spin/run.sh` are A01-A14 (design configurations) and X01-X11 (mutations). A* avoids colliding with `holds.pml` (H01-H13).

## Summary (paste-ready, under 4,000 characters)

```text
Card 1125 activity_history: draft protocol and SPIN check (auditor). Design only; nothing built.
Model: `verify/spin/activity_history.pml`, 25 checks, all as expected (results below, and `verify/spin/README.md`).

1. Table activity_history: id, type (mail|todo), activity_id, rev, base_rev, field (body|detail|done_when), kind (create|edit|supersede|note), desk_id, at (UTC), diff (old to new), bytes_old, bytes_new, fp (MILL_FP of the new text). UNIQUE (type, activity_id, rev). Written by the same procedure, under the same row lock, as the payload update. Append only.
2. Version: mail.rev and todo.rev, 1 at create, +1 on every text change (edit, supersede, done-when, note). rev is the fingerprint.
3. Reads return rev from the same SELECT as the text. The client sends --rev = the rev of the text it last showed, not the highest rev it heard. Default output adds one line, "v3, edited by DESK 2h ago". Old text only via --history or trail --history.
4. Writes:
- Text replace (edit, supersede, done-when): compare-and-set on rev under the lock. A stale rev is refused with the diff since your rev and the command to retry.
- Note append: never refused, rev+1.
- Reply, claim, pass, ship, done: always apply. If behind, return stale=true, the diff since --rev, and record base_rev on the move/reply row.
5. Notify: an edit queues one edited hint per (item, desk) for everyone on it except the editor: mail_to rows (asked and copied) plus sender; todo asker, volunteer, watchers. Not the whole room. Debounce: one pending slot per (item, desk); a later edit overwrites it, and the hint carries the final rev plus the diff from that desk's last told rev. Rings only addressed desks, as wake_on does now.
6. Unread: add seen_rev to mail_to and watcher; unread = seen_rev < rev. It advances on a read or an act at the current rev, never on hint delivery (hints drop). Do not clear mail_to.opened (A11: a second receipt).
7. Receipts: unchanged, one per row at first open. --history shows each row's seen_rev.
8. Rights: replace = author/asker or Admin (as #656 for mail); notes as now. Refusals name the next command.
9. Done items: the asker or Admin may edit; status stays; everyone is notified. Retired or deleted: refused (card:deleted), with a reclaim hint.

Builder suggestions:
(1) rev, not hash: TAKE. It orders versions and lets the server send only the diff since --rev. Keep fp in history for a replay check.
(2) Refuse only text edits; stale flag on claim/pass/reply: TAKE, plus base_rev stored on the act so a check can flag "shipped against v2, now v3".
(3) Debounce: TAKE with the slot rule. Keeping the first rev drops the final one (X07). Unread state is written at edit time, never deferred.
(4) The no-v-1 property: TAKE, as P1. Proved for the design; it fails if the check runs outside the lock (X01), or if body and rev come from two selects (X02).
Refuse vs stale flag: refuse only text replaces (lost update, P3). Stale-flag everything else; refuse mode can refuse a reply every time while edits continue (A09).

Findings for builder:
F1 a reply locks nothing on the parent today (mill_mail_insert); the rev check needs the parent row locked.
F2 rev must come from the same SELECT as the body (mill_mail_open, todo reads); a second query breaks P1 (X02).
F3 todo has no per-desk read state; use seen_rev on watcher, not a new table.
F4 an older hint landing after a newer read must be dropped by rev (X09).
F5 marking seen on hint delivery breaks P2 when hints drop (X08); hint_drop is a live score.
F6 an edit is not a note today (notes are append-only, #539); decide whether replace is new or reuses --supersedes.

Open: does a note append re-notify, and does it count as unread-again? Stale reply text: full or diff only? Debounce window length? Does an Admin edit of someone else's letter need a reason line?
```

## 1. What exists today (main e028bac)

- `mail.body` and `todo.body` are VARCHAR(4096). `todo.body` is a JSON payload; `detail` holds the note lines and `done_when` is its own column.
- `mill_mail_update` locks the editing desk's seat, then the letter (FOR UPDATE). Only the sender or an Admin desk may change it (#656). It writes act `note` on activity. Nothing calls it from the CLI, it notifies nobody, and it leaves `mail_to.opened` alone.
- `mill_todo_write` locks the seat, then the card. It refuses `card:deleted` under the lock and sets `body = IFNULL(p_body, body)`, so the last writer wins.
- `mill note` is append-only. `--replace` is refused (#539), and corrections go through `--supersedes OLD_LINE --note NEW`.
- `mill_mail_open` locks the `mail_to` row, keeps the first open (IFNULL), pushes at most one receipt, and returns `m.body` in its final SELECT.
- `mill_mail_insert` (send and reply) takes no lock on the parent letter.
- `watcher` covers todo, doing, hold and score, but not mail. Mail's per-desk rows are `mail_to` (asked or copied).
- `transition.meta` is capped and must not hold text, so text history needs its own table. That matches the human's decision.

## 2. Table

```sql
CREATE TABLE activity_history (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type        ENUM('mail','todo') NOT NULL,          -- grows with text-bearing types
  activity_id BIGINT UNSIGNED NOT NULL,
  rev         SMALLINT UNSIGNED NOT NULL,            -- the rev this row produced
  base_rev    SMALLINT UNSIGNED NOT NULL,            -- the rev the writer saw (rev-1 for a clean write)
  field       ENUM('body','detail','done_when') NOT NULL,
  kind        ENUM('create','edit','supersede','note') NOT NULL,
  desk_id     BIGINT UNSIGNED NOT NULL,
  at          DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  diff        TEXT NOT NULL,                         -- old -> new, unified; bounded by two 4096-char texts
  bytes_old   INT UNSIGNED NOT NULL,
  bytes_new   INT UNSIGNED NOT NULL,
  fp          CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,  -- MILL_FP(new text)
  PRIMARY KEY (id),
  UNIQUE KEY idx_rev (type, activity_id, rev),
  KEY idx_desk (desk_id, at),
  CONSTRAINT fk_history_activity FOREIGN KEY (type, activity_id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_history_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
);
ALTER TABLE mail    ADD rev SMALLINT UNSIGNED NOT NULL DEFAULT 1;
ALTER TABLE todo    ADD rev SMALLINT UNSIGNED NOT NULL DEFAULT 1;
ALTER TABLE mail_to ADD seen_rev SMALLINT UNSIGNED NOT NULL DEFAULT 0;
ALTER TABLE watcher ADD seen_rev SMALLINT UNSIGNED NOT NULL DEFAULT 0;
```

- The procedure writes the history row in the same transaction and under the same row lock as the payload UPDATE. If it doesn't, `--history` can end at an older text than the payload, and two edits can append out of order (X06).
- `UNIQUE (type, activity_id, rev)` is the structural guard for P3 and P4. A second row from the same base fails on insert even when the code's compare is wrong.
- The current text lives only on the payload. Older versions are rebuilt by applying diffs backward from it. A deterministic check, `history_replay`, walks every item, rebuilds each rev, and compares it with `fp`. It needs no model and no trust in the diff tool.
- Alpha, so there is no migration of old edits. Existing rows start at `rev = 1` with no history row; `create` rows are written from 0.8.13 on.

## 3. Version semantics

- `rev` starts at 1 when the item is created and goes up by one on every text change: `edit` (replace), `supersede`, `done_when`, and a `note` append.
- A note append bumps rev because it is text an agent has not seen. Appends are never refused, so this only affects stale flags and hints, never whether a write lands. (See open question Q1.)
- Status moves, claims and receipts do not bump rev. rev versions the text, not the state.
- `rev` is the fingerprint the human asked for. A hash would only say "different". rev says how far behind a desk is, so the server can return just the history rows after `--rev`, which is usually far smaller than the full text. That's the token point of the card.

## 4. Read and write API

The verbs show, mail, and edit below are proposed names; they are not in the current CLI (reads today go through `mill todo`, `mill mail-thread`, `mill inbox`, and `mill trail`; there is no edit verb).

Reads (`mill show`, `mill mail N`, `mill todo ID`, inbox, `trail`): <!-- doc-commands: skip -->
- Return `rev` with the text, from the same SELECT on the payload row (F2, X02).
- Default text output gets one line, `v3, edited by DESK 2h ago`, only when rev > 1. No history rows.
- `--history [--page N]` lists history rows newest first: `rev, at (office clock), desk, kind, +bytes/-bytes, diff clipped to 200 chars`, 20 per page.
- `--rev K` prints the text as it stood at rev K.
- `trail` nodes add `rev` and `edited: true` when rev > 1. `trail --history` adds the newest history row per node, clipped.

The client keeps `last_rev[item]`, the rev of the text it last showed the agent: from a read, a stale or refusal reply, or an edited hint it showed. On every act it sends that as `--rev` unless the agent gives one explicitly. It must not keep the highest rev it has heard (X09).

Writes:

| Verb | On `--rev` < current | Reply |
| :--- | :--- | :--- |
| `mill edit ID TEXT --rev N` / `mill mail N --edit` / `--supersedes` / `--done-when` | refused, nothing changed | `stale: you have vN, current vM; diff since vN below; retry: mill edit ID --rev M ...` | <!-- doc-commands: skip -->
| `mill note` (append) | applied, rev+1 | `stale=true` and the diff since vN, if behind |
| reply, claim, unclaim, pass, ship, done | applied | `stale=true`, the diff since vN (or the full text when shorter), `base_rev` stored on the reply letter or move row |
| no `--rev` at all (old client, hand call) | treated as stale | same as above; the hint says to pass `--rev` |

Every stale reply also advances that desk's `seen_rev` to the current rev, because the reply carries the text.

## 5. Notify and unread

- **Who gets the edited hint:** everyone on the activity except the editor. For mail: all `mail_to` rows (asked and copied) plus the sender. For todo: watcher rows, which already include the asker (creator via `mill_watcher_roster`), the volunteer and any watcher. Room members who are not on the item get nothing, which keeps the cost down.
- **Hint body:** `edited ITEM vM by DESK`, plus the diff from that desk's last-told rev. It falls back to the full new text when that's shorter or the desk was never told.
- **Debounce:** one pending slot per (item, desk). A later edit overwrites the slot's rev; it never keeps the first one (X07). It flushes when the window ends or when the hub next runs for that desk. The window length is open (Q3).
- **Wakes:** an edited hint rings only desks that the item addresses (`wake_on addressed`), the same as other hints. Watchers get it at their next connect.
- **Unread:** derived, `unread = seen_rev < rev` (on `mail_to` and `watcher`).
  - `seen_rev` advances on a read of the item, or on an act carrying `--rev` = current.
  - It never advances on hint delivery. Hints can drop (the live `mill-desk.hint_drop` score), and a dropped hint must leave the item unread (A03, A04, X08).
  - The edit writes unread at edit time, simply by bumping rev. Nothing about unread waits for the debounce flush.
- **Do not reset `mail_to.opened`.** It keeps the first open. Clearing it to show "unread again" pushes a second receipt on the re-read, which breaks mail invariant 7 (A11).

## 6. Edit rights

- Replace (edit, supersede, done-when): the author (letter sender, card asker) or an Admin desk. That matches `mill_mail_update` and `cmd_card_accept` now.
  - A refusal names the next command: `not yours to edit; add a note: mill note ...` or `reply: mill mail N --reply`. <!-- doc-commands: skip -->
  - An Admin edit of someone else's text stores the Admin desk in `desk_id`, so `--history` shows who.
- Note append: unchanged.
- The volunteer may not replace the asker's text. It notes instead, so the asker's acceptance line can't silently move under it.

## 7. Done and retired

- **Done (or shipped):** the asker or Admin may edit. Status doesn't change, the edit notifies everyone on the item, and `--history` marks the edit "after done".
  - The ship or done move row records `base_rev`. A check (F7) flags a card whose `done_when` changed after the ship's `base_rev`, which is a cue for the Validator.
  - This is a check, not a gate.
- **Retired or deleted:** edits and acts are refused under the lock (`card:deleted`), with the hint `mill reclaim ID (Admin)`. The text is frozen (P6, A06, X10).

## 8. Receipts

There is still one receipt per `mail_to` row, at first open. An edit sends no new receipt. The sender can see who has read the latest version in `mill mail N --history`, which lists each row's `seen_rev` against `rev`. <!-- doc-commands: skip --> It's a read, not a push, to save tokens.

## 9. Races (what the model covers)

| Race | Rule | Check |
| :--- | :--- | :--- |
| edit vs edit, same base | CAS under the row lock; UNIQUE (type, id, rev) | P3, X04, X05 |
| edit vs reply or claim | the act compares `--rev` under the item lock (a reply must lock the parent: F1); applies with stale=true | P1, X01, X03 |
| read vs edit | body and rev from one row read | P1, X02 |
| edit vs history writer | same procedure, same lock | P4, X06 |
| hint in flight vs newer read | the client drops a hint older than `last_rev` | P1, P5, A05, X09 |
| hint dropped | unread covers it | P2, A03, A04, X08 |
| burst of edits | slot keeps the last rev | P5, X07 |
| edit vs retire | refused under the lock | P6, X10 |
| refuse mode under edit churn | can starve the act | A09 vs A10 |

Lock order: every new path keeps the F183 order (the acting desk's seat, then the item). A reply locks its own seat, then the parent letter, FOR SHARE. That's enough against an edit's FOR UPDATE, and it adds no new pair to `tools/sql_lock_order.py`.

## 10. Verdicts on builder's suggestions

1. **Monotonic rev instead of a hash: take it.** Ordering lets the server send the diff since `--rev` rather than the whole text. Keep `fp` per history row for the replay check. A hash also hides the case where text is edited back to an earlier version.
2. **Refuse only text edits; stale flag for claim, pass and reply: take it,** with two additions. Store `base_rev` on the act's row, so the record shows what the desk saw. Treat a missing `--rev` as stale, so old clients get the flag rather than silence. Refusing acts is safe (A08) but can refuse the same reply again and again while the text keeps changing (A09). Stale-flag always lands (A10) and follows hints over gates.
3. **Debounce consecutive edits into one hint: take it,** with the slot rule. The key is (item, recipient), not (item, editor), and the last rev wins. The hint's diff is from the recipient's last-told rev, not from the previous edit. Unread is never deferred. Keeping the first rev fails P5 (X07).
4. **SPIN property "no desk acts on v-1 without being told v exists": take it,** as P1, stated as "an act is accepted clean only if the desk's last text is the current text". The precise form matters. With the client keeping the highest rev it heard (X09), or body and rev read apart (X02), the desk was "told v exists" by rev number but never saw v's text.

**Refuse vs stale flag:** refuse text replaces only, because that's where a lost update is real (P3). Apply everything else with `stale=true` and the diff.

## 11. Findings

See Findings below: each finding with its owner and the check that catches it.

## 12. Open questions for the team

- Q1. Does a note append re-notify, and does it make the item unread again? This proposal bumps rev, so an act after someone's note is flagged stale with just that note. Hints for notes stay as they are today.
- Q2. Stale and refusal replies: always the diff, or the full text when the desk is more than K revs behind?
- Q3. Debounce window: a fixed number of seconds, or until the editor's next non-edit command?
- Q4. Should an Admin edit of another desk's text require a one-line reason, kept in the history row?
- Q5. Should a `done_when` change after ship move the card back to claimed? This draft says no: a check flags it (F7) and the Validator decides.
- Q6. Retention: keep history forever (text is small and capped at 4096), or prune with the 30-day sweep?
- Q7. The `mail` and `todo` ENUMs in the new table: add `score` notes later, or keep text types only?


---

# Card 1125 findings (design holes the model and the code read turned up)

Owner for every item: builder (build of card 1125). The auditor reviews against `verify/spin/activity_history.pml`.

| # | gap | evidence | fix | check that catches it |
| :--- | :--- | :--- | :--- | :--- |
| F1 | A reply takes no lock on its parent letter (`mill_mail_insert`), so a `--rev` check on the parent would read outside the lock and could pass a stale reply as clean | X01 (check before lock fails P1); code read of sp_mail.sql | reply locks the parent `mail` row FOR SHARE after its own seat and compares `--rev` there | SPIN X01 kept failing; a two-connection SQL test: edit commits between the reply's read and insert, and the reply must come back `stale=true` |
| F2 | If rev comes from a different query than the text, a desk can hold rev 2 with text 1 and act "clean" | X02 | `rev` comes from the same SELECT as `body` in `mill_mail_open`, the todo get, page and trail reads | a static check (`tools/` grep): every procedure that SELECTs `mail.body` or `todo.body` also selects `rev` in the same statement |
| F3 | todo has no per-desk read state, so "unread again" has nowhere to live for cards; mail has `mail_to.opened`, but reusing it breaks receipts | A11 (second receipt), A12 | `seen_rev` on `mail_to` and `watcher`; unread = `seen_rev < rev`; leave `opened` as the first open | SPIN A11 stays violated and A01 passes; a test: edit, re-read, exactly one receipt row |
| F4 | An edited hint taken before a newer read can land after it; a client that keeps the max rev then acts clean on text it never saw | X09; A05 passes with the drop rule | hints carry `rev`; the client drops a hint older than `last_rev[item]` and sends the rev of the text it last showed | SPIN X09/A05; a client unit test: deliver read v2 then hint v1, the next act sends `--rev 2` and shows v2 text |
| F5 | Treating hint delivery (or queuing) as "seen" loses unread when a hint drops; drops are real (`mill-desk.hint_drop`) | X08, A04 | `seen_rev` advances only on a read or an act at the current rev | SPIN X08; a test: queue an edited hint, drop it, the inbox still shows the item unread |
| F6 | No "edit" exists for cards: notes are append-only by rule (#539) and `mill_todo_write` replaces the whole body with no base check (last writer wins) | code read; X04 shows the lost update | one replace path (`mill edit` or `--supersedes`) doing CAS on rev; decide whether `--supersedes` becomes that path | SPIN X04/X05; UNIQUE (type, activity_id, rev) makes a double apply fail on insert | <!-- doc-commands: skip -->
| F7 | A ship or done made against an older acceptance line is invisible after the fact | design (suggestion 2) | store `base_rev` on the move row (doing) and the reply letter | a deterministic check: list cards whose `done_when` history row has rev > the ship's `base_rev`; report, do not refuse |
| F8 | Refusing stale acts can refuse the same reply/claim again and again while edits continue | A09 vs A10 | stale-flag for acts; refuse only text replaces | SPIN A09/A10 kept in the run |
| F9 | `mill_mail_update` notifies nobody and writes act `note`; with this card it must write history, bump rev and queue hints in the same transaction | code read; X06 (history after commit) | history row, rev bump and hint queue in the edit procedure itself, not an after-commit hook | SPIN X06; the `history_replay` check (rebuild every rev from the diffs, compare `fp`) |
| F10 | The debounce slot must be keyed per recipient and keep the last rev; keyed per editor or keeping the first, a burst ends with desks told an old rev | X07 | one slot per (item, desk), last rev wins, diff from that desk's last told rev | SPIN X07/A02; a test: two edits inside the window, one hint, carrying the final rev |


---

# activity_history.pml results (card 1125, design model)

Run: the 25 A* and X* rows of `verify/spin/run.sh` (about 45 s, under 200 MB; the full suite is 127 checks and about 15 minutes). spin 6.5.1, gcc, `-DCOLLAPSE`,
exhaustive (no BITSTATE, no depth cut; max depth 300000, deepest reached 161). Last full suite run 2026-11-10 (Pacific).
Every check matched its expectation. Trails are not committed; `verify/spin/run.sh A09` (or any violated id) prints the trail. Known: `run.sh` exits 0 when a property is violated if that is the listed expectation, so read the expect/got columns, not only the exit code.

Model bounds: 3 desks (author/asker A, addressee/claimer B, watcher with Admin W), one item,
up to 2 author edits (3 in A07, A13, A14) plus 1 watcher edit, a reply or claim carrying `--rev`,
re-reads, a Hub that delivers debounced edited hints (may drop them, may land them late), done or retire.

## Properties

| Id | Property | How checked |
| :--- | :--- | :--- |
| P1 | No act (reply, claim, pass) made at rev v-1 is accepted silently once v exists: it is refused or flagged stale and the reply carries the current text | assert in the act's lock step: accepted clean implies the desk's last text is the current text |
| P2 | Every desk on the activity was told the last rev, or still sees the item unread | assert at rest (timeout) |
| P3 | No lost edit: at most one text edit applies from any base rev | assert in the edit's lock step |
| P4 | History is append-only, one row per rev, newest row = current text | assert in every read and edit, and at rest |
| P5 | Debounce never drops the final rev: with no dropped hints, every desk ends told the final rev | assert at rest (`CHECK_P5`) |
| P6 | A retired item's text never changes | assert at rest |
| P7 | One receipt per recipient row, also after an edit makes it unread again (mail invariant 7) | assert in the read |
| act_lands | The reply/claim lands (not refused MAXTRY times in a row) | LTL safety claim `[] !gaveup` |

## Results

| Id | Defines | Expect | Got | States | Depth | What it shows |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| A01 | (proposed design) | pass | pass | 49,630 | 110 | P1, P2, P3, P4, P6, P7 |
| A02 | CHECK_P5 | pass | pass | 49,630 | 110 | P5: one pending slot per (item, desk), last rev wins |
| A03 | HINT_DROP=1 | pass | pass | 83,903 | 110 | P2 with hints that drop: unread covers the untold desk |
| A04 | HINT_DROP=1 CHECK_P5 | violated | violated | 44 | 110 | expected: a dropped hint leaves a desk untold; why unread must stay |
| A05 | INFLIGHT=1 CHECK_P5 | pass | pass | 202,760 | 116 | a hint that lands after a newer read is dropped by rev |
| A06 | CLOSE=2 | pass | pass | 71,528 | 110 | retire refuses edits and acts; text frozen |
| A07 | EDITS_A=3 | pass | pass | 170,258 | 134 | A01 with three author edits |
| A08 | ACT_MODE=1 | pass | pass | 79,469 | 120 | refuse mode is also safe |
| A09 | ACT_MODE=1 | violated | violated | 10,555 | 161 | finding: refuse mode starves a reply/claim while edits continue |
| A10 | ACT_MODE=0 | pass | pass | 49,630 | 146 | stale-flag mode: the act lands on its first try |
| A11 | SEEN_REV=0 | violated | violated | 2,755 | 121 | finding: unread-again by clearing mail_to.opened sends a second receipt |
| A12 | SEEN_REV=0 SKIP_P7 HINT_DROP=1 | pass | pass | 82,923 | 121 | that reuse keeps P2 when it clears every handled row |
| A13 | EDITS_A=3 INFLIGHT=1 HINT_DROP=1 CLOSE=2 | pass | pass | 1,777,811 | 142 | larger: P1-P4, P6, P7 |
| A14 | EDITS_A=3 INFLIGHT=1 CHECK_P5 | pass | pass | 969,136 | 142 | larger: P5 |
| X01 | MUT_CHECK_SPLIT | violated | violated | 10,419 | 110 | act compares `--rev` before the item lock (P1) |
| X02 | MUT_READ_SPLIT | violated | violated | 65,393 | 113 | read returns body and rev from two selects (P1) |
| X03 | MUT_SILENT | violated | violated | 10,051 | 110 | stale act applies with no flag (P1) |
| X04 | MUT_EDIT_NOCAS | violated | violated | 210 | 110 | edit ignores its base, last writer wins (P3) |
| X05 | MUT_EDIT_SPLIT | violated | violated | 633 | 110 | edit compares its base before the lock (P3) |
| X06 | MUT_HIST_SPLIT | violated | violated | 208 | 113 | history row written after commit (P4) |
| X07 | MUT_DEB_FIRST CHECK_P5 | violated | violated | 71 | 116 | debounce keeps the first rev (P5) |
| X08 | MUT_SEEN_ON_HINT HINT_DROP=1 | violated | violated | 44 | 110 | queuing the hint marks the desk seen (P2) |
| X09 | INFLIGHT=1 MUT_KNOWS_MAX | violated | violated | 189,857 | 127 | client keeps the highest rev heard, even from an older hint (P1) |
| X10 | CLOSE=2 MUT_EDIT_RETIRED | violated | violated | 64 | 110 | edit on a retired item applies (P6) |
| X11 | SEEN_REV=0 SKIP_P7 HINT_DROP=1 MUT_NO_UNREAD_W | violated | violated | 44 | 119 | unread-again clears addressee rows only (P2) |

Every property has at least one mutation that breaks it, so no pass is vacuous.

## What is not modelled

- Text contents and diffs (text is an id per rev); the diff chain replay is a deterministic check, not a model.
- Append-only notes as a separate op (they are a text change with rev+1 and never refused; see the protocol above).
- Edit rights (a guard in the procedure; not concurrent).
- Wake POSTs and the lease (wake.pml covers them); the Hub here is the delivery of the hint frame only.
- More than one item, rooms with many members, time windows (debounce is "pending slot until the Hub runs").
