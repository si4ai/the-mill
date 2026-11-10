---
name: model-antigravity
description: >
  Antigravity (agy) runtime delta for the mill. Use with mill-desk, not instead of it.
  Connect-shell binding and minimum safe permissions only.
---

# Antigravity

Office behavior is [skill.md](../../skill.md). This file is only what this runtime does differently. Do not copy the office into here.

Placement for an office repo is in [howto-ai.md](../../howto-ai.md) (Google - Gemini CLI / Antigravity). Session start is `mill briefing`.

**Seat borrow.** A command with no sitting connect opens the joined desk's seat for that one command and releases it (same rule as [skill.md](../../skill.md)). It fails if another connect already holds the seat. Long `mill connect` stays optional for presence and hints. If a one-shot command fails with `no sitting mill connect for this process`, the desk is not joined on that host; join first.

`tw` is not a mill command and does not borrow the seat: it needs a sitting `mill connect` for this process (see [skill.md](../../skill.md)).

**Minimum safe permissions (mill side).** Intent for an office desk doing the user's own work:

- allow: `mill` commands (`command(mill)`)
- deny: `git push`, `git merge`, and `gh pr merge`
- ask: everything else (rely on the default ask fallback; do not put `command(*)` in ask, or it overrides the mill allow - deny > ask > allow)

Example `~/.gemini/antigravity-cli/settings.json` snippet (placeholders only; schema at https://antigravity.google/docs/permissions/):

```json
{
  "agentMode": "accept-edits",
  "toolPermission": "request-review",
  "permissions": {
    "allow": ["command(mill)"],
    "deny": [
      "command(git push)",
      "command(git merge)",
      "command(gh pr merge)"
    ]
  }
}
```
