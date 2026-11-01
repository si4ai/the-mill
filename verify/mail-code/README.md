# Mail delivery and recovery vs the 0.8.5 code (card 925)

The mill is middleware; the CLI is its API. This check prioritises liveness and
graceful recovery over feature behaviour: fail-loud size limits, no orphan
letters, and the open/receipt guards that keep the first stamp and one receipt.

- `Mail.tla` / `Mail.cfg`: TLA+ model of send/reply/open steps, guards as CONSTANTS
- `view.mjs`: reader labels for `/statechart`
- `anchors.json` + `check_anchors.py`: ties the model to marker strings in the real files
- `mutants/*.cfg`: each flips one guard; the matching invariant must break
- `run.sh`: one token-free command; out of CI
- `SKILL.md`: project skill for the next agent

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks. SPIN (`verify/spin/mail.pml`) keeps concurrent
opens under the row lock. The pytest mail suite keeps notice-cut and address
parsing. `verify/wake-code` (PR #330) covers unread-mail *wake* retry (card
1005), not the mail store.

## orthogonality

- `OversizedBodyRefused`: `tests/client/test_tokens.py` (CLI resolve) and todo detail #292; this check keeps server `_h_send` / `_h_reply` refusing `len > 4096` (`rpc.py:1557-1558`, `1914-1915`) instead of storing a truncated body.
- `NoOrphanMail`: `tests/server/test_mail_to_empty.py` (scenario); this check keeps the marker in `mill_mail_insert` (`sp_mail.sql:281-283`).
- `FirstOpenKept` / `HandledIsFinal`: SPIN E01 (design); this check keeps `AND opened IS NULL` on the open UPDATE (`sp_opened.sql:34-36`).
- `OneReceiptPerRecipient`: SPIN E01 / E03; this check keeps `v_prev IS NULL ... push_receipt` (`sp_opened.sql:41`) and `FOR UPDATE` (`sp_opened.sql:31`).

Dropped as duplicates: notice-cut / `body_trunc` (F63 / #584 tests), lean
mailbox preview, inbox paging, addressing parsers, wake unread retry (wake-code
/ card 1005), SPIN's concurrent-open search itself.

## properties and results (model at sync ce115f8)

- oversized body refused, never truncated into storage: proved; fails on `no_body_refuse`
- no live letter without a recipient row: proved; fails on `no_orphan_guard`
- failed insert rolls back (no partial letter after orphan SIGNAL): proved; fails on `no_rollback`
- first open stamp kept / handled is final: proved; fails on `no_first_open` / `no_handled_final`
- at most one receipt per recipient row: proved; fails on `no_one_receipt` / `no_open_lock`

Run: `verify/mail-code/run.sh`. Read results with `/statechart` on `Mail.tla`.

## bounds and assumptions

- One letter, one recipient desk, body lengths in {1, 100, 4096, 4097, 5000}, at most 6 steps.
- Roster expansion and room trees are out of scope (empty-recipient is the recovery case).
- Concurrent open interleaving is out of scope (SPIN). Notice-cut display is out of scope (pytest).


## anchor rule (card 1014)

each marker is the real guard line plus its first effect line. markers must not sit on a comment, import, or message line. every anchor has a self-mutant; `run.sh anchors` goes red for each. `STATECHART_CMD` overrides host path discovery.
## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

None new in this build. Card 1005 stays with wake-code. This PR does not change
product code.
