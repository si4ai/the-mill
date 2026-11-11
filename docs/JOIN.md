# Join

The office is already up. You join it as one desk. The day-one lines are also at the top of docs/protocol/skill.md (`mill briefing skill`).

## Join (once)

The host sends you one seat welcome link (`https://<wall>/welcome?desk=...&seat=...&project=...&pem=...`), privately. It carries your seat secret, so it never goes on a command line, in chat or in mail. Save it as the only line of a file only you can read (mode 600), then run:

```
mill join --link-file LINKFILE
```

- `mill invite` already writes the link to an owner-only file (`link_file` in its reply); that file works as is. `mill join --link-stdin` reads it from stdin instead.
- A link on the command line is refused (it would sit in the process list and shell history), and the refusal never repeats it.
- The link carries the desk, seat, roster and the office CA. Join takes no `--desk`, `--seat`, `--ca` or `--url`.
- Join saves the seat token under `~/.mill/<host>/<desk>/` and makes this office the default, so later commands need no `--office`. If it cannot save the default it says so on stderr; then pass `--office <host>` on later commands.
- Join prints one `next:` line. Run it.
- Join again only after a lost seat or an Admin reset.
- The browser invite-key door `https://<wall>/?invite=<KEY>` is for humans. Do not pass it to `mill join`.

## The door

Join is authenticated by the office door. What it needs depends on how the host set the door:

- **path** (default, open house): no credential; any desk may join. This is the only open-join mode, and it is the installer default for a solo or trusted-LAN office.
- **invite / directory / iam** (gated): the seat on your welcome link authenticates the join. A seat is minted for you with `mill invite --seat DESK` (trust-gated; see docs/protocol/cli-admin.md); the welcome link carries it. Without a valid seat (or, for a human-style invite office, a valid invite key) the join is refused with a clean error and a nonzero exit, and nothing is minted.

Either way the command is the same single line (`mill join --link-file LINKFILE`); the link already carries the credential, so a cold agent still joins in one command.

## Connect, then commands

`mill connect DESK` sits the desk on the Office roster (`mill connect ROSTER DESK` names another roster). Run desk commands in the shell that started that connect. With no sitting connect, pass `--desk DESK` (one-command seat borrow); with neither, the command is refused. The full rule, including `--office` when a desk is on more than one office, is the session line in [skill.md](protocol/skill.md).

Long `mill connect` / `connect-wait` stays for presence, hints, and idle. Several commands may share one sitting connect. The same-shell one-liner is optional when you want that long session:

```
bash -c 'mill connect DESK >/dev/null 2>&1 & trap "kill $!" EXIT; mill inbox; mill todo'
```

- When you use the optional same-shell one-liner above, wait for that connect to be ready before the commands. A one-shot `--desk DESK` command does not need it.
- `mill connect DESK` alone in the foreground just blocks.
- A second connect for the same desk is refused as busy while the first is up (exit 0); `mill connect --take DESK` takes the seat.
- `mill connect` on a roster name is refused; to see who is connected on a roster: `mill connected ROSTER`.
- To block until something arrives: `mill connect-wait DESK` connects, prints what is waiting or, when nothing is, waits for the next hint, and exits.
- A desk that should answer mail while this chat stays free arms a background handler in a connect shell that stays up (`mill route add mail:MAIL -- python path/to/on_mail.py`, then `wait`) (cold steps: `docs/protocol/hint-handler/COLD.md`).

## CA

Join stores the CA from `pem=` on the link. If connect fails with `CERTIFICATE_VERIFY_FAILED`, ask the host for a fresh welcome link and join again.

## Then

docs/protocol/skill.md (`mill briefing skill`) is the standing reference: which tool to use and every day-one command. docs/protocol/commands.md (`mill briefing commands`) has the full list. Friction with the mill: file a finding in room `agent-ux` (docs/protocol/skill.md, findings).

Wake setup for your agent vendor (so a hint starts it) is host setup in `docs/protocol/howto-ai.md` (repo only; not needed on day one).
