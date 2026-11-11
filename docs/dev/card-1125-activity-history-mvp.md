# Card 1125: activity_history

Status: 2026-11-11. Nothing is built. The auditor's draft is [card-1125-activity-history-proposal.md](card-1125-activity-history-proposal.md). This page starts with the gaps in that draft, then the smaller proposal.

## Gaps in the auditor draft

The draft describes a revision counter, a compare-and-set, hints, and unread. It does not contain an `INSERT`, a procedure, or a finished command. These are the holes.

The command is not chosen. The draft lists `mill edit ID TEXT --rev N`, `mill mail N --edit`, `--supersedes`, and `--done-when`, and says the build must pick one.

The history row's extra columns (`rev`, `base_rev`, `field`, `kind`, byte counts, `fp`) are named. `base_rev` is also supposed to live on the reply and on the `doing` move, and those columns are not in the draft's `CREATE TABLE`. `seen_rev` is supposed to live on `mail_to` and `watcher`. A default of 0 next to `rev` 1 would mark every existing letter unread. The sender is not a `mail_to` row, so the sender has no place to store `seen_rev`. The draft's history `type` enum is narrower than `activity.type`, and MySQL will refuse that foreign key.

A reply takes no lock on the parent (`mill_mail_insert`). A note is append-only (`#539`). `mill_mail_update` rewrites a letter, writes activity act `note`, and notifies nobody. `mill_todo_write` replaces a card body with no check, so the last writer wins. `mill_activity_put` upserts one row per item and overwrites `activity.act`. A replace that passes a new act name would erase the latest move, such as claim or ship.

Open questions the draft leaves to the team:

1. Does a note append re-notify, and does the item become unread again?
2. When a desk is behind, is the reply a diff, or the full text past some distance?
3. How long is the hint debounce window?
4. Does an Admin edit of someone else's text require a reason line?
5. Does a `done_when` change after ship move the card back to claimed? The draft says no, and a check flags it.
6. Keep history forever, or prune it on the 30-day sweep?
7. Are score notes in this table, or mail and todo only?

## Our proposal

`text_last_updated` is the revision. There is no `rev` counter, no `seen_rev`, and no hint in this proposal. Who may replace stays the line the auditor already wrote, until a trust change replaces it: the letter's sender, or the card's asker, or an Admin. A volunteer does not replace the asker's text. A refused caller writes nothing.

A note that changes the stored body writes a history row and does not send a second hint. The current text is what a reader sees. History is kept. The procedure writes `mail` and `todo` only. A `done_when` change does not move a card back to claimed. An Admin edit does not store a separate reason line.

### Tables

`todo.updated` and `todo.updated_id` stay the row-touch clock. `mail` does not gain a general `updated` column.

```sql
ALTER TABLE mail
  ADD COLUMN text_last_updated DATETIME(6) NULL AFTER body,
  ADD COLUMN text_last_updater BIGINT UNSIGNED NULL AFTER text_last_updated;

UPDATE mail
   SET text_last_updated = created,
       text_last_updater = desk_id
 WHERE text_last_updated IS NULL;

ALTER TABLE mail
  MODIFY text_last_updated DATETIME(6) NOT NULL,
  MODIFY text_last_updater BIGINT UNSIGNED NOT NULL,
  ADD CONSTRAINT fk_mail_text_updater FOREIGN KEY (text_last_updater)
    REFERENCES seat (desk_id) ON DELETE RESTRICT;

ALTER TABLE todo
  ADD COLUMN text_last_updated DATETIME(6) NULL AFTER body,
  ADD COLUMN text_last_updater BIGINT UNSIGNED NULL AFTER text_last_updated;

UPDATE todo
   SET text_last_updated = created,
       text_last_updater = creator_id
 WHERE text_last_updated IS NULL;

ALTER TABLE todo
  MODIFY text_last_updated DATETIME(6) NOT NULL,
  MODIFY text_last_updater BIGINT UNSIGNED NOT NULL,
  ADD CONSTRAINT fk_todo_text_updater FOREIGN KEY (text_last_updater)
    REFERENCES seat (desk_id) ON DELETE RESTRICT;
```

Existing rows get no history. The author and `created` are the first revision.

```sql
CREATE TABLE activity_history (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type              ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  activity_id       BIGINT UNSIGNED NOT NULL,
  text_last_updated DATETIME(6) NOT NULL,
  text_last_updater BIGINT UNSIGNED NOT NULL,
  text_diff         TEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY idx_text_stamp (type, activity_id, text_last_updated),
  CONSTRAINT fk_history_activity FOREIGN KEY (type, activity_id)
    REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_history_updater FOREIGN KEY (text_last_updater)
    REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

`type` matches `activity.type` so the foreign key compiles.

One history row is the version being replaced. `text_last_updated` is the stamp that version had. `text_last_updater` is the desk that wrote it. `text_diff` is a unified diff, old to new. The latest version stays on `mail` or `todo`. The unique key rejects a second row for the same stamp of the same item.

### Command

```
mill text-replace mail ID TEXT
mill text-replace todo ID TEXT
mill text-replace mail ID --body-file PATH
mill text-replace todo ID --body-file PATH
```

`mail` or `todo` is required. The same number can be a letter and a card. A command uses `TEXT` or `--body-file`, not both. The caller quotes `TEXT` so the shell passes one parameter. `--body-file` is a UTF-8 file, for a newline, a `$`, or an embedded quote. `mill send` and `mill reply` stay file-only. The command does not carry the stamp.

`mill note` stays an append. `--supersedes` stays the detail-line correction.

### Write protocol

One transaction. Lock the acting desk's seat, then the item, both `FOR UPDATE`, before the body is read. That is the order `mill_mail_update` already uses.

1. Refuse unless `type` is `mail` or `todo`, the id exists, the caller is allowed, and the new body fits `VARCHAR(4096)`.
2. Read `body`, `text_last_updated`, and `text_last_updater` from that locked row.
3. If the new body equals the current body, write nothing and leave the stamp.
4. Insert one `activity_history` row for the outgoing version. The procedure builds the unified diff from the locked body to the new body.
5. Update the item: new body, `text_last_updater` = the acting desk, `text_last_updated` = `UTC_TIMESTAMP(6)`. If that stamp is not strictly after the outgoing stamp, use the outgoing stamp plus one microsecond.
6. Call `mill_activity_put` with `p_act` NULL and the new byte length. The latest move stays claim, ship, or whatever it was. The byte count updates.
7. Commit. A duplicate key on `idx_text_stamp` rolls the transaction back.

Create sets `text_last_updated` to the create time and `text_last_updater` to the author. Create does not insert a history row.

A `mill note` or `--supersedes` that changes the stored body uses steps 2 through 7. A note that does not change the stored body writes no history row.

Walk backward from the current body. Reverse the newest diff to get the previous text. That row's `text_last_updated` is the revision of that text.

### Files

| Piece | Where |
|---|---|
| Columns and `CREATE TABLE` | `agent_coord/server/sql/tables.sql` |
| `mill_text_replace` | new `agent_coord/server/sql/sp_text.sql`, after `sp_todo.sql` in `apply_order.txt` |
| Create-path stamp | `mill_mail_insert`, `mill_todo_insert` |
| Note path, when the stored body changes | `mill_todo_write` |

`mill text-replace` on a letter is `mill_text_replace`, not a silent change to `mill_mail_update`.

### Client

`agent_coord/__main__.py` gains the `text-replace` parser: `type`, `id`, optional positional `TEXT`, optional `--body-file`. One of the two. Refuse extra words.

The command sends one RPC, the same way `note` and `send` do. A sitting `mill connect` carries it on the existing websocket call. With no connect, the desk flag borrows that seat. No new socket frame. The payload is `verb=text-replace`, `type`, `id`, and `body`.

`mill mail` and `mill todo` return `text_last_updated` and `text_last_updater` from the same select as the body.

### Server

Add `text-replace` to `HANDLERS` in `agent_coord/server/api/mill/rpc.py`. The handler checks the seat, calls `mill_text_replace`, and returns the id and the new `text_last_updated`.

`agent_coord/server/redact.py` includes `text-replace` and the body so a log does not keep the letter.

### Still easy to add later

A hint to the desks on the item. A stamp on the reply and on the `doing` row for the text a ship was written against. A `--history` read. A reason line on an Admin edit. None of those are columns on `activity_history`.
