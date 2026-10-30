# Optimization guide

How to make mill reads and writes faster, and a log of the cases found so far.
Contributors append to the log during every optimization loop.

## Principles

1. The database filters, counts and checks existence. Code never selects rows
   and then loops to find, drop, count or test them. Put the condition in the
   WHERE clause, use EXISTS for yes/no, and LIMIT 1 when one row is enough.
2. Fetch only the rows and columns the caller uses. Leave out bodies and JSON
   blobs from list reads; fetch a body only for the ids that are returned.
3. One read per question per request. Do not read the same tree, roster or
   catalog twice in one command; read it once and pass it down.
4. No N+1. One query with `IN (...)`, a join or a grouped derived table, not a
   query per id and not an HTTP call per roster.
5. Index the filter and the order together, for example `(desk_id, opened, id)`
   for "unread for this desk, newest first". Weigh every index against the
   table's write rate; hot write tables (activity, push_queue, tree) get none
   without a measured win.
6. Read the plan. Run `EXPLAIN FORMAT=TREE` and `EXPLAIN ANALYZE` and look for
   table scans, filesort or temporary tables over rows that carry bodies, and
   rows examined far above rows sent. If the planner picks a bad plan, change
   the query shape (for example a derived table that drives from the index)
   rather than wrapping it in more code.
7. Measure before and after on a throwaway copy of the book, with the same
   data and at least 20 runs, and diff the command output so the result stays
   identical. Drop any trial index when the test ends. This is a timing
   measurement; the SQL A/B in [HOST.md](../install/HOST.md#stored-procedures)
   gates the live apply, not the writing (CI `pytest_sql` covers that).

## Examples log

One entry per finding. Append new entries at the end; update `Status` when a
fix ships. Paths and lines are at the commit named in the entry. Timings are
server-side on the throwaway copy unless marked "client"; client estimates
use about 30 us per wide row and 13 us per narrow row (pure-Python driver).

Entry format:

    ### N. Short title
    - Pattern: which principle it breaks
    - Where: path:lines (at <sha>)
    - Rows: fetched -> used
    - Before: ms   After (expected or measured): ms
    - Fix: the SQL or code change
    - Status: open | fixed in <version> (<PR>)

### 1. Room read fetches the whole room to answer yes/no questions
- Pattern: 1, 2, 3
- Where: `agent_coord/server/api/mill/rpc.py:1190-1300` (mail-thread),
  `agent_coord/server/records/mail.py:429-494, 608-620, 687-751, 780-837`,
  `agent_coord/server/admin/guard.py:27-34` (at 6e6acda)
- Rows: participant check on a 719-letter room reads 719 letters with bodies
  and 4,246 recipient rows -> 1 boolean; visibility reads them again; crumbs
  and the tree are read 3 to 4 times per request
- Before: recipient read 9.1 ms, letters 2.0 ms, each tree read 0.95 ms, plus
  about 18k rows of client parsing. After: participant EXISTS 0.20 ms,
  ids-only cast 3.4 ms, one tree read 0.86 ms
- Fix: one tree read per request; EXISTS for participant and admin checks;
  visibility from (mail id, sender id, recipient id) without names or bodies;
  bodies only for the returned ids
- Status: fixed in 0.7.4 (!78). One tree read per request, participant and admin
  checks as EXISTS, names-only cast. Measured on the copy, client median, 719-letter
  room: room read 200 -> 48 ms, outsider refusal 32 -> 8.5 ms, admin read 137 -> 31 ms

### 2. Inbox fetches the whole mailbox, then drops read letters in code
- Pattern: 1, 2, 5, 6
- Where: `agent_coord/server/sql/sp_mail.sql:388-411`,
  `agent_coord/server/api/mill/rpc.py:221-268` (at 6e6acda)
- Rows: busiest desk 1,281 -> 0; others about 1,000 -> 100; bodies on every row
- Before: 8.3 to 11.8 ms (filesort of all rows). After: rewrite alone 1.3 to
  1.8 ms; rewrite plus index 0.12 to 0.51 ms
- Fix: `KEY mail_to (desk_id, opened, id)` and drive from it:
  `SELECT ... FROM (SELECT id, receipt FROM mail_to WHERE type='mail' AND
  desk_id=? AND opened IS NULL ORDER BY id DESC LIMIT ?) t JOIN mail m ...`.
  A flat join let the planner start from mail and cost 3.1 ms
- Status: fixed in 0.7.4 (!79). mill_mail_inbox pages unread from
  `idx_desk_unread (desk_id, opened, id)`; `--all` keeps its newest-100 order and
  unread keeps oldest-first (the audit's `--all` note was wrong; unchanged). 0.7.17 (card 846): unread is newest-first too, a backward scan of the same index.
  Measured on the copy, client median: desk with nothing unread 15.4 -> 1.2 ms,
  busy desks 25-29 -> 12-17 ms, `--limit 5` 13-21 -> 2.6-4 ms, `--all` 32-37 ->
  20-21 ms. What is left is the recipient and crumbs reads (entry 13, 10)

### 3. Todo list filters done cards, rosters and search text in code
- Pattern: 1, 2, 4
- Where: `agent_coord/server/api/mill/rpc.py:308-405`,
  `agent_coord/client/http.py:558-634`, `agent_coord/server/sql/sp_todo.sql:254-291` (at 6e6acda)
- Rows: default list 248 -> 103 (145 done cards with about 870-byte bodies
  dropped); id peek 248 -> 1; `--all` makes one call per live roster (14)
- Before: 3.7 ms per roster call plus 15 round trips for `--all`.
  After: 1.5 ms with `status <> 'done'` (existing index), 0.5 ms for an id peek, one call
- Fix: SP parameters for hide-done, id, need and find text, fixture rosters
  excluded in SQL; `--all` is one call with an empty roster
- Status: fixed in 0.7.4 (!81) for done and id: mill_todo_page drops done cards and
  reads one card in SQL; `--all` sends every roster in one call (up to 200 rosters
  per call). The client reads only that `{cards}` answer: the per-roster loop for
  an older wall was removed in 0.7.5. Need-name and find text still match in
  code. Measured on the copy, client median: `--all` 26.1 -> 6.3 ms (15 calls -> 2), `--all --done` 29.6 -> 9.0 ms, list 5.8 -> 3.6 ms, id peek
  5.8 -> 1.5 ms

### 4. Send scans every seat to read one desk's last update
- Pattern: 1, 2
- Where: `agent_coord/server/api/mill/rpc.py:840-867` (at 6e6acda)
- Rows: up to 70 seats with recent-activity JSON -> 1 timestamp per recipient
- Before: 2.9 to 3.4 ms. After: under 0.05 ms
- Fix: `SELECT desk_id, updated FROM join WHERE desk_id IN (...)`
- Status: fixed in 0.7.4 (!82). One seat read by desk id for the whole dest list
  (member join when a project is named). Measured on the copy, client median:
  send to one desk 4.4 -> 1.1 ms, desk outside the project 5.4 -> 1.4 ms; a
  24-desk reply-all 10.8 -> 9.6 ms (now the per-desk name lookups)

### 5. Connect and hold peek read every hold
- Pattern: 1
- Where: `agent_coord/server/records/hold.py:31-80`,
  `agent_coord/server/api/mill/rpc.py:1726-1750`,
  `agent_coord/server/records/floor.py:1794-1810` (at 6e6acda)
- Rows: 18 -> 0 to 2 (one desk, one resource, or held rows only)
- Before: 0.32 ms plus label subqueries. After: 0.03 to 0.05 ms
- Fix: `WHERE h.desk_id = ?`, `WHERE h.resource_id = ?`, `WHERE h.desk_id IS NOT NULL`
- Status: fixed in 0.7.4 (!82). hold own, peek, drop, the held list and floor holds
  read by WHERE; exact name compare kept. At 18 rows: 0.8-1.1 -> 0.5-0.7 ms client.
  With 2,018 hold rows: own and peek 10-15 -> about 0.9 ms

### 6. Whole name catalog loaded to check one roster
- Pattern: 1, 2
- Where: `agent_coord/server/api/mill/rpc.py:35-57, 443-453`;
  `agent_coord/server/records/floor.py:732, 1066-1073, 1546-1547, 1660, 1945` (at 6e6acda)
- Rows: 326 -> 1 boolean
- Before: 0.19 ms plus about 4 ms client. After: 0.028 ms
- Fix: `SELECT 1 FROM name WHERE type='roster' AND name=? AND deleted IS NULL`;
  list rosters only to build the refusal text
- Status: fixed in 0.7.4 (!82) for the rpc checks: one idx_type lookup on the
  happy path, rosters-only list for the refusal and `project`. Project check
  1.3 -> 0.3 ms, `project` command 2.2 -> 0.7 ms. The floor id-to-name maps still
  load the catalog (open)

### 7. Fanout scans the 40 newest activity rows for one row
- Pattern: 1
- Where: `agent_coord/server/push.py:314-337`,
  `agent_coord/server/sql/sp_activity.sql:118-137`;
  same shape in `agent_coord/server/records/floor.py:1722-1791` (at 6e6acda)
- Rows: 40 (table scan and filesort of 2,388) -> 0 or 1
- Before: 1.18 ms. After: 0.07 ms (primary key lookup)
- Fix: `SELECT ... FROM activity WHERE type=? AND id=?`. An index on
  `activity(updated)` was tried and not used by the planner; activity is the
  hottest write table, so no index
- Status: fixed in 0.7.4 (!75). mill_activity_get, a const primary-key read:
  1.27 -> 0.24 ms server, 1.67 -> 0.50 ms client; finds the 293 of 300 sampled
  activities the newest-40 scan missed

### 8. Mark checks each id with a full letter fetch and a loop
- Pattern: 1, 4
- Where: `agent_coord/server/api/mill/rpc.py:2432-2450` (at 6e6acda)
- Rows: letter, body and every recipient per id, two calls per id -> 1 boolean per id
- Before: 2 procedure calls per id. After: one primary key query for all ids (0.03 ms)
- Fix: `SELECT id FROM mail_to WHERE type='mail' AND desk_id=? AND id IN (...)`
- Status: open

### 9. Room name lookups read the whole tree
- Pattern: 1, 2
- Where: `agent_coord/server/api/mill/rpc.py:915-936, 1060-1080, 1424-1432, 2321-2325` (at 6e6acda)
- Rows: up to 719 -> 1
- Before: 0.95 ms plus about 9 ms client. After: 0.03 to 0.10 ms
- Fix: `EXISTS`, `WHERE name_id=? AND lft=1`, or
  `WHERE name_id=? AND type='mail' ORDER BY lft LIMIT 1` (covering index)
- Status: open

### 10. Tree crumbs join is quadratic
- Pattern: 3, 6
- Where: `agent_coord/server/records/mail.py:249-284, 780-802` (at 6e6acda)
- Rows: 525,331 examined, 6,213 sent for 719 letters
- Before: 84 ms. After: one tree read 0.86 ms plus a stack walk in code
- Fix: read the room once ordered by lft and derive root and parent per node;
  no index makes the range join linear
- Status: partly fixed in 0.7.4 (!78): mail-thread derives crumbs from its one
  tree read. Inbox and other batch callers still use the join

### 11. Push requeue filters JSON on every queued row
- Pattern: 5, 6
- Where: `agent_coord/server/records/push.py:69-140`,
  `agent_coord/server/sql/sp_mail.sql:313-315` (at 6e6acda)
- Rows: 833 examined -> 0 or 1 (2,185 for the letter delete)
- Before: 0.8 to 1.4 ms, no index used. After: a point lookup
- Fix: later, a stored generated column for the payload id plus
  `KEY (desk_id, kind, ref_id)`; first drain undelivered frames
- Status: open

### 12. Wall mail fingerprint scans all mail
- Pattern: 1, 6
- Where: `agent_coord/server/sql/sp_floor_scope.sql:80-101, 286-298` (at 6e6acda)
- Rows: all 7,282 recipient rows, semijoin with OR re-planned per row
- Before: 18.2 ms (part: 42 ms). After: 11.9 ms with a UNION of two indexed lookups;
  less with a fingerprint from activity per desk
- Fix: UNION rewrite now; fingerprint from activity once recipient adds stamp activity
- Status: open

### 13. Recipient read sorts every row by name
- Pattern: 6
- Where: `agent_coord/server/records/mail.py:370-397` (at 6e6acda)
- Rows: 4,246 sorted for 719 letters
- Before: 9.1 ms. After: 6.9 ms without the ORDER BY
- Fix: sort the few recipients per letter in code, or drop the sort
- Status: open

### 14. Every push take swept the whole queue for expired rows
- Pattern: 3, 5
- Where: `agent_coord/server/sql/sp_mail.sql` (mill_push_take, at 6e6acda)
- Rows: every desk's queued rows on each take -> this desk's rows only
- Before: about 12 ms added to each command. After: the take reads and deletes
  only the caller's rows
- Fix: `mill_push_expire` drops rows past 30 days for every desk; the Wall runs
  it at start and every 12 hours (regression row F17)
- Status: fixed in 0.7.4 (!74)

### 15. Command reply waited on the score write; callproc cost extra round trips
- Pattern: 3, 4
- Where: `agent_coord/server/asgi.py`, `agent_coord/server/middleware.py`,
  `agent_coord/server/records/db.py` (at 6e6acda)
- Rows: a 4-5 statement score write awaited before every reply; `callproc`
  added `SET @_arg` and `SELECT @_arg` round trips to each procedure call
- Before: reply waited 3.4-4.1 ms; mill_hold_select 0.9-1.1 ms. After: under
  0.01 ms; 0.6-0.7 ms
- Fix: park the score on the 1 s flusher and write batches on one connection;
  `call()` issues one CALL statement (no procedure has OUT parameters)
  (regression row F24)
- Status: fixed in 0.7.4 (!84)

### 16. The office host ran the book on the pure-Python driver
- Pattern: driver, not SQL
- Where: `agent_coord/server/records/driver.py`, `mill wall` startup
- Rows: every book call. The connector C extension failed to import on an
  OpenSSL 3.0 host (bundled OpenSSL 3.2+ vs the system libssl that ssl loaded
  first), and the connector fell back to pure Python without a word
- Before -> after (pure -> C, handler medians on a copy of the book): inbox 11.9 ->
  6.9 ms, todo page 4.3 -> 2.9 ms, a 719-letter room thread 49.2 -> 26.2 ms, send
  7.3 -> 6.5 ms
- Fix: C extension by default; `mill wall` restarts once with the bundled
  OpenSSL preloaded; the active driver shows in /health, the mill-perf startup
  line and one warning line on fallback; CI requires the C path (regression row F34)
- Status: fixed in 0.7.5
