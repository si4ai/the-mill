# Grok Build foreground mail

Office behavior is [skill.md](skill.md). This file is only the Grok Build foreground delta. Regression row F27 (grok-foreground-shipped-forms).

The idle rule is the background wait bullet in skill.md. This file does not repeat it.

Grok Build has no direct message from one chat into another. A poke is mill MAIL to that desk. The other desk wakes when its own `mill connect` is up. The `/ws` room is the bare desk name.

- Idle: one background `mill connect-wait`, owned by the session. The chat stays free. The wait exits on one work HINT.
- Background with a session: `mill connect <desk> --vendor grok-build --session <Grok-session-UUID>` runs `grok -p "HINT..." -r UUID` for that session. That starts a new process. It does not enter an open chat.
- No connect: the letter stays in the book until a later connect takes the sync.

A second connect with the same seat token is refused as busy while the first is up; `--take` closes the first: `DISCONNECTED`, reason `superseded: new connect same tokenHash`.

## Which wake fits

The choice is the pick-your-wake bullet in skill.md. Checked against vendor docs on 2026-10-23; recheck before relying on a row.

| Runtime | Background process, told when it exits | Inbound POST | Schedule | Wake |
| :--- | :--- | :--- | :--- | :--- |
| Grok Build | yes (Ctrl+B; the exit wakes the chat, F27) | no | unknown | background wait |
| Grok Bot | `mill-hold` only (grok-bot/SKILL.md) | routine webhook | routines | webhook |
| Claude Code | yes (`Monitor` feeds each output line) | cloud scheduled task API trigger | `/loop`, desktop and cloud scheduled tasks, `claude -p` | background wait in a terminal session; webhook in the cloud |
| Gemini CLI | yes when `tools.shell.backgroundCompletionBehavior` is `inject` (default `silent`) | no | `gemini -p` from cron | background wait with `inject`; else schedule |
| Codex CLI | background terminals (`/ps`); exit notice unknown | no | `codex exec` from cron | schedule, or block |
| Cursor | agent background unknown | Automations webhook trigger | Automations schedule | webhook |
| Aider | unknown | no | `aider --message` from cron | schedule, or start of turn |

Sources: Claude Code code.claude.com/docs/en/tools-reference (`Monitor` tool), /interactive-mode (background Bash), /scheduled-tasks, /web-scheduled-tasks (API trigger), /headless; Gemini CLI geminicli.com/docs/reference/configuration (tools.shell.backgroundCompletionBehavior), /docs/tools/shell (is_background), /docs/cli/headless; Codex learn.chatgpt.com/docs/developer-commands (/ps), developers.openai.com/codex/noninteractive; Cursor cursor.com/docs/cloud-agent/automations; Aider aider.chat/docs/scripting.

## Sit

The session starts the wait in the background (Ctrl+B) and owns it; on Windows a wait started by a shell that then exits dies with `parent exited`. `Ctrl+B`, and a new chat line, each move the running command to the background and open the chat. Stopping the process drops the socket. Esc does not cancel mill connect.

```
mill connect-wait YOUR-DESK
```

Replace `YOUR-DESK` before running. The desk sits on the Office roster of the office this computer joined (`mill join` sets it); no roster or office word is needed. One HINT returns, the process exits, and the chat wakes. A letter has `"kind":"mail"`. `kind: sync` is a JSON list, the push queue. Non-empty: print it and exit, so the chat wakes with the drain. Empty: hold the socket until the next hint. A missed JOIN inside that list is a queue item, not a frame to ignore.

`connect-wait` does not publish the reply bridge. A reply needs a normal connect in the same shell. Start that connect with `python -m agent_coord` from a directory that is not the checkout, and clear `PYTHONPATH`. Leave it up until the reply returns. Then stop that connect and start the wait again (a connect still up makes the wait busy). `mill` and `python -m agent_coord` both see it; keep the connect and the reply in the same shell. One connection that holds the seat and runs the commands is card 703.

```
python -m agent_coord connect YOUR-DESK
python -m agent_coord reply MAIL_ID --body-file RESULT.txt
mill connect-wait YOUR-DESK
```

## Reminder

One reminder per desk, in that desk's Grok session. It does not wake other chats. It runs while that session is open. A durable reminder runs once when the session opens again. A closed PC does not sit.

The note arrives after the current turn ends, so a healthy wait is not cut off. After a stop, disarm that session's reminder.

Each run checks the live process list for `connect-wait YOUR-DESK` on `mill.exe` or `python.exe`. Up: one line `FOREGROUND-UP YOUR-DESK`. Down: one line `FOREGROUND-DOWN YOUR-DESK`, then start the wait again. Its first sync drains what queued. The reminder never opens a short connect.
