# Card 1125: replace-body with activity_history (MVP design)

Status: the MVP the team agreed in room `card-1125-mvp` (letters 5384-5408) and on cards 1125 (`card-edit-replaces`, done_when) and 1133 (`card-1125-schema`, decisions 1-8). Targeted at 0.8.14. Nothing is built. This doc is the design and the SPIN model's account of it; the card done_when is what the Validator measures. Model: `verify/spin/activity_history.pml`, checks A01-A09 and X01-X15 in `verify/spin/run.sh`.

The verbs `replace-body` and `--history` below are not in the current CLI yet. <!-- doc-commands: skip -->

## 1. What changes

- One command: `mill replace-body mail|todo ID (TEXT | --body-file PATH)`. Mail and card text change only through it. <!-- doc-commands: skip -->
- The note command is deleted from the CLI (no appends, no `--supersedes`); card text changes only with `mill replace-body`, and `mill todo ROSTER NEED --eta/--started/--progress/--done-when` sets the card's own fields (card 1125, 8:19 AM PST decision). Old text goes to history instead of staying inline marked superseded.
- One new table, `activity_history`, with the full old body per write. No diffs: a diff cannot be written atomically inside the procedure; one can be computed on read from two rows later.
- `mail` and `todo` get `body_updated DATETIME(6) NULL` and `body_updater_id` (FK seat). `body_updated` is the version: NULL means never edited.
- todo: `body` becomes the card text (the old JSON `detail`); a new `meta` column holds the rest of the JSON (slug, progress, eta, started_at, aliases). Status, volunteer and claim time stay in their columns.

## 2. Table (card 1133)

`activity_history(id PK, type ENUM('mail','todo'), activity_id, old_body VARCHAR(4096), old_updated DATETIME(6), old_updater_id, replaced_at DATETIME(6), replaced_by)`

- Append-only. One row per body write, holding the body that write replaced and that body's stamp.
- `UNIQUE (type, activity_id, old_updated)`: the structural guard against a lost update when two versions carry the same stamp (A06, A07).
- `FK (type, activity_id) -> activity(type, id) ON DELETE CASCADE`; desk FKs to seat `RESTRICT`. Purge is the only hard delete.
- Schema through `migration.sql`, idempotent: a second install is a no-op, and the todo JSON split is byte-equal and skips rows already moved.

## 3. The write: one procedure, one transaction

Every body write runs one stored procedure. In one transaction it:

1. locks the seat, then the item row (`FOR UPDATE`), the same order as today;
2. refuses a retired item, or a desk that is neither the sender/asker nor Admin, with nothing changed and no history row;
3. compares the caller's `body_updated` with the row's, NULL-safe (`<=>`). On a mismatch it refuses `body:stale` and changes nothing. The refusal names the next command: `body:stale: edited by DESK at TIME; re-read with mill mail-thread ID (or mill todo ID --full), then retry`;
4. inserts the history row (`old_body`, `old_updated`, `old_updater_id`, `replaced_at`, `replaced_by`);
5. writes `body`, `body_updated = MILL_NOW()` and `body_updater_id`, and the activity row as today (act `replace`).

The caller's `body_updated` is the desk's last read of that item, which the client keeps per `(type, id)` on disk so it survives a `--desk` one-shot. With no last read, `replace-body` is refused with the exact read command. It never re-reads inside the call: that would stamp the agent's older text as current (X08). <!-- doc-commands: skip -->

Only `replace-body` can be refused stale. <!-- doc-commands: skip -->

- A bare claim writes status, volunteer and eta only, never `body` or `body_updated`.
- Any line a claim adds (take-over line, `--msg`) is appended inside the same lock from the current body, never from an earlier client read. It writes a history row and a new `body_updated` like any body write, so a replace built on the text before it is refused.

## 4. Reads

- A read (`mill mail-thread N`, `mill todo ID --full`, glance and inbox JSON) returns `body`, `body_updated` and `body_updater_id` from the same SELECT, and the client records the stamp as the last read.
- Default output adds one line, `edited by DESK at TIME`, only when `body_updated` is set. The Wall reads the same two fields and paints the same line.
- Old text only on an explicit history ask (later: `--history`; the Wall's old-versions view on card 1134). <!-- doc-commands: skip -->

## 5. Receipts

A body write never touches `mail_to.opened` or receipts. An edit does not make a letter unread again and sends no second receipt (X07).

## 6. What the model checks

`verify/spin/activity_history.pml`: one item, three desks: A (sender or asker), B (addressee or claimer, no edit right), W (Admin). A and W each read, then replace, re-reading and retrying after a refusal; W may skip the read. B reads, then either claims bare, claims with an in-lock line, or tries a replace it has no right to. B reads again, so a second receipt would show. A may retire the item. The clock (`MILL_NOW()`) is strict by default; `CLOCK=1` lets it repeat or step back. Searches are exhaustive.

| Property | How checked |
| :--- | :--- |
| P1. A read returns body and `body_updated` of one version | assert in the read |
| P2. Only the sender/asker or Admin replaces | assert in the replace step |
| P3. No lost update: every body write is built on the current text, so no replace, claim line or other replace silently undoes another | assert in the write step (the text's base is the current version); at rest the versions form one chain |
| P4. History is the item's log: one row per body write, the newest row is the version the current one replaced, with its stamp | assert in every read and at rest |
| P5. A retired item's body never changes | assert at rest |
| P6. A replace built on the current text, by a desk with the right, on a live item, is never refused | assert in the replace step (`CHECK_P6`) |
| P7. One receipt per `mail_to` row, also after edits | assert in the read and at rest |

Results (spin 6.5.1, `-DCOLLAPSE`, max depth 300000; every row matches its expectation):

| Id | Defines | Expect | Got | States | Depth | What it shows |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| A01 | (MVP design) | pass | pass | 4,059 | 89 | card 1125 MVP: P1 one-SELECT read, P2 rights, P3 no lost update, P4 history = log, P7 receipts; replace, in-lock claim line, bare claim |
| A02 | APPEND=0 | pass | pass | 1,933 | 79 | replace-only (card 1125, 8:19 AM PST: no note append): same properties |
| A03 | CLOSE=1 | pass | pass | 6,914 | 93 | retire: replace refused afterwards, body frozen (P5) |
| A04 | FAIL=1 | pass | pass | 12,841 | 116 | forced error after the history insert rolls back both (done_when 5) |
| A05 | CHECK_P6 | pass | pass | 4,110 | 89 | P6: a replace built on the current text is never refused stale (strict clock) |
| A06 | CLOCK=1 | pass | pass | 6,196 | 94 | MILL_NOW() may repeat or step back: UNIQUE (type, activity_id, old_updated) still stops every lost update |
| A07 | CLOCK=1 UNIQUE=0 | violated | violated | 692 | 68 | FINDING: body_updated alone is not a version when the clock repeats; the UNIQUE key is load-bearing |
| A08 | CLOCK=1 CHECK_P6 | violated | violated | 648 | 75 | FINDING (minor): a repeated stamp makes UNIQUE refuse a replace built on the current text |
| A09 | CLOSE=1 FAIL=1 MAXTRY=3 | pass | pass | 40,563 | 163 | larger: retire, forced errors, three tries per editor |
| X01 | MUT_APPEND_RMW | violated | violated | 1,838 | 86 | mutation: the claim/note line is appended to an earlier unlocked read (P3) |
| X02 | MUT_CLAIM_RMW | violated | violated | 2,175 | 86 | mutation: a claim rewrites the body from its earlier read, as today (P3) |
| X03 | MUT_NOCAS | violated | violated | 34 | 62 | mutation: replace ignores body_updated, last writer wins (P3) |
| X04 | MUT_CAS_SPLIT | violated | violated | 56 | 66 | mutation: replace compares body_updated before the item lock (P3) |
| X05 | MUT_READ_SPLIT | violated | violated | 35 | 66 | mutation: a read takes body and body_updated from two selects (P1) |
| X06 | MUT_HIST_SPLIT FAIL=1 | violated | violated | 13 | 34 | mutation: the history row commits in its own transaction (P4) |
| X07 | MUT_OPEN_CLEAR | violated | violated | 185 | 75 | mutation: a body write clears mail_to.opened, a second receipt (P7) |
| X08 | MUT_FRESH_READ | violated | violated | 37 | 64 | mutation: replace-body re-reads body_updated in the call, not the last read (P3) |
| X09 | MUT_NULL_NE | violated | violated | 34 | 62 | mutation: compare cur <> base; NULL never reads as stale (P3) |
| X10 | MUT_NULL_EQ CHECK_P6 | violated | violated | 10 | 20 | mutation: compare cur = base; a never-edited item is always stale (P6) |
| X11 | MUT_ANY_RIGHTS | violated | violated | 1,023 | 86 | mutation: no rights check (P2) |
| X12 | CLOSE=1 MUT_EDIT_RETIRED | violated | violated | 90 | 79 | mutation: replace on a retired item applies (P5) |
| X13 | MUT_APPEND_NOBUMP UNIQUE=0 | violated | violated | 1,706 | 72 | mutation: the append leaves body_updated as it was, a replace from before it passes (P3) |
| X14 | MUT_APPEND_NOBUMP | violated | violated | 1,706 | 83 | same with the UNIQUE key: on a never-edited item old_updated is NULL and NULLs never collide, so the append is still lost (P3) |
| X15 | MUT_NOREAD_NULL | violated | violated | 98 | 81 | mutation: no last read is sent as NULL; on a never-edited item a desk replaces text it never read (P3) |

A07 and A08 are expected violations (findings below). X01-X15 are mutations: each property has at least one mutation that breaks it, so no pass is vacuous.

## 7. What the model found

1. **The UNIQUE key is load-bearing, not decoration (A06, A07).** `body_updated` is a timestamp, and a timestamp is a version only while the clock never repeats. If `MILL_NOW()` returns a value an earlier version had (clock stepped back, or two writes in one microsecond), a desk holding that older stamp passes the compare and overwrites newer text. Counterexample (A07): A and W both read version 2 (stamp t). W replaces; its stamp repeats t. A's replace compares t = t, passes, and W's text is lost. With `UNIQUE (type, activity_id, old_updated)` A's history insert collides with W's row and nothing changes (A06 passes). Keep the key, and map its duplicate-key error to `body:stale` with the re-read command.
2. **NULL is the one stamp the key never guards (X09, X10, X14, X15).** A never-edited item has `body_updated` NULL, and NULLs never collide in a MySQL UNIQUE key. So the first edit rests on the compare alone, and the compare must be NULL-safe: `<>` lets a stale replace through when either side is NULL (X09); `=` refuses every first edit (X10). The client must also tell "read an unedited item" (NULL) from "no last read" (refuse): sending NULL for both lets a desk replace text it never read (X15). Any in-lock append must stamp `body_updated` too; with the key alone, an append that keeps the NULL stamp is still lost (X14).
3. **Minor (A08):** with a repeating clock, the key also refuses a replace that was built on the current text, when the current stamp equals an older replaced one. The item stays refused until another write takes a fresh stamp. Only possible when the clock repeats; no change asked.
4. **Done_when item 1 needs an owner's decision.** It still asks that a note during a replace land as the replaced text plus the note. The 8:19 AM PST decision removes the note append path, and grok-tui asked in 5407 what item 1 should measure. The model covers both: with the in-lock claim line (A01) and replace-only (A02). If the claim's take-over or `--msg` line stays, item 1 can measure that line in its place.

## 8. Check id mapping (from the first draft)

The first draft modelled hints, debounce, `seen_rev` and stale-flagged acts. Those features left the MVP, so their checks left `run.sh` and the README. They return when the features do. Old to new:

| Old | Now |
| :--- | :--- |
| A01 (design) | A01 (MVP) |
| A02, A04, A05, A14, X07 (debounce, P5) | deferred: edit hints |
| A03, A12, X08, X09, X11 (hint drop, unread, seen_rev) | deferred: edit hints and unread-again |
| A06, X10 (retire) | A03, X12 |
| A07, A13 (larger) | A09 |
| A08, A09, A10, X01, X03 (acts carrying `--rev`, stale flag or refuse) | deferred: acts no longer carry a version; a claim does not write the body (X02) |
| A11 (unread-again clears `opened`) | X07 (a body write must not clear `opened`) |
| X02 (read split) | X05 |
| X04, X05 (edit without CAS, CAS before lock) | X03, X04 |
| X06 (history after commit) | X06 |

New: A02 (replace-only), A04 (forced error after the history insert), A05-A08 (no false stale, clock repeats), X01 (append from an unlocked read), X08 (fresh read in the call), X09-X11, X13-X15.

## 9. Not modelled

Text contents (a version is an id); the todo JSON split and the second install (deterministic tests on card 1133); the `--desk` one-shot keeping the last read (a client test); more than one item; Wall rendering; act `replace` counted in `commands_used`.

## 10. Later, only if needed

Diffs computed on read from two history rows; `--history` paging; edit hints to watchers and addressees with debounce; unread-again through a per-desk `seen_rev` (never by clearing `opened`); acts that carry a version with a stale flag; history pruning. Each brings back its deferred checks.
