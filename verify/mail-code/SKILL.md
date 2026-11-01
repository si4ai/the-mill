---
name: verify-mail-code-recovery
description: Check that the mill's mail send/reply/open guards still implement fail-loud body size limits, no orphan letters, first-open kept, and one receipt per recipient. Use when a change touches rpc.py _h_send/_h_reply/_h_mark, sp_mail.sql mill_mail_insert, or sp_opened.sql mill_mail_open, or when someone asks whether an oversized letter is refused, an empty recipient set can leave an orphan row, or a second open can rewrite the first stamp or double a receipt.
---

# verify mail delivery and recovery against the code

## Why TLA+ here

`verify/spin/mail.pml` models concurrent opens under the row lock. Pytest covers
notice-cut and addressing. This check asks whether the *real* rpc and SQL
guards still enforce fail-loud size limits, no orphan letters, and the
first-open / one-receipt rules those assume. Package:

1. Models each indivisible send/reply/open step in TLA+, citing `path:lines`.
2. Ties the model to the code with `anchors.json`.
3. Shows each property failing on a deliberately broken copy.
4. Is read with the pstack `/statechart` skill.

## does my change touch the covered code?

Sync commit (in `run.sh` as `SYNC`, currently ce115f8eb70e7e360b80974ec62e177e7771199f):

- body refuse: `rpc.py` `_h_send` / `_h_reply` (1557-1558, 1914-1915)
- orphan refuse: `sp_mail.sql` `mill_mail_insert` (281-283)
- open lock + first stamp: `sp_opened.sql` `mill_mail_open` (29-36, 41)

## properties (plain)

- `OversizedBodyRefused`: an oversized body is truncated into storage instead of refused
- `NoOrphanMail`: a letter row exists with no `mail_to` recipient
- `FirstOpenKept` / `HandledIsFinal`: a second open rewrites the first stamp (handled is not final)
- `OneReceiptPerRecipient`: two opens push two receipts for one recipient row

## Run

    verify/mail-code/run.sh
    verify/mail-code/run.sh anchors
    verify/mail-code/run.sh model
    verify/mail-code/run.sh mutant no_body_refuse

## Read a result

Use `/statechart` on `verify/mail-code/Mail.tla` (config `Mail.cfg`, or
`Mail-chart.cfg` for a small chart; view `view.mjs`).

## Change the model when the code changes on purpose

1. Edit the TLA+ action for the changed step.
2. Update `anchors.json`.
3. Run `verify/mail-code/run.sh`. Keep every mutant failing.
4. Move `SYNC` forward only after the model and anchors match that commit.

## findings stay findings

Report counterexamples as cards. Do not weaken invariants. Do not change
product code unless asked.

## Out of scope

- Concurrent open search (SPIN). Notice-cut / lean preview (pytest).
- Wake unread retry (verify/wake-code, card 1005).
- CI: on demand only.
