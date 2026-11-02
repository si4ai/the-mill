---
name: model-antigravity
description: >
  Antigravity (agy) runtime delta for the mill. Use with mill-desk, not instead of it.
  Connect-shell binding and minimum safe permissions only.
---

# Antigravity

Office behavior is [skill.md](../../skill.md). This file is only what this runtime does differently. Do not copy the office into here.

Placement for an office repo is in [howto-ai.md](../../howto-ai.md) (Google - Gemini CLI / Antigravity). Session start is `mill briefing`.

**Connect-shell binding.** mill commands must run as children of the shell that started `mill connect` (same rule as [skill.md](../../skill.md)). If Antigravity's terminal tool starts a new shell per call, those commands fail with `no sitting mill connect`. That is the first failure to look for. Keep connect and the mill command in one terminal call, for example `bash -c 'mill connect DESK >/dev/null 2>&1 & trap "kill $!" EXIT; mill COMMAND'`, or confirm the tool keeps one parent shell across calls.

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

Do not restate rule triggers, frontmatter, the full settings schema, app presets, or `agentMode` here. Those live in Google's docs and change on Google's schedule: https://antigravity.google/docs/rules/ , https://antigravity.google/docs/skills/ , https://antigravity.google/docs/permissions/ , https://antigravity.google/docs/cli/reference/ .
