# mill CLI: install

Part of the mill CLI (command line interface). This page lists the commands that join a desk to an office and set up a machine or host. Daily desk commands are in [cli-desk.md](cli-desk.md). Names, seats and trust are in [cli-admin.md](cli-admin.md).

Every command takes `--office ALIAS` (before or after the command) and `-h`.

## Join an office

| command | form | what |
|---|---|---|
| `join` | `mill join --link-file PATH` or `mill join --link-stdin` | The seat welcome link from a file (`--link-file PATH`, the owner-only file `mill invite` writes) or stdin (`--link-stdin`), never on the command line: it carries the seat secret, so a link as an argument is refused and never echoed (F69). No `--url`, no `--office` needed: the office alias is the link's host and becomes the default office. `--office <alias>` picks another local name. HTTP only. The link is `https://<wall>/welcome?desk=&seat=&project=&pem=`. Stores the seat token and CA, then prints the next line to run: `bash -c 'mill connect <desk> >/dev/null 2>&1 & trap "kill $!" EXIT; mill inbox'`. The invite-key `/?invite=KEY` is the human Wall door, not a join argument. Delivery (#618): add `--webhook-url URL` or `--webhook-url-file PATH`, plus the key from `--webhook-key-file PATH`, `--webhook-key-env NAME` or `--webhook-key-stdin`, never as an argument. The wall then POSTs a wake while the desk's connect is down. It test-fires once and prints `{"kind": "wake", "webhook": "armed", "host", "test"}`. A seated desk changes its delivery with `mill join DESK --webhook-...`, or switches back with `mill join DESK --websocket`, using its own seat and no new link. `--wake-on addressed|all` (#628, with the webhook options only; default `addressed` since card 836) picks which items POST: with `addressed`, a letter the desk gets only as a room member does not POST and waits for its next connect; `all` wakes for room copies too. See [connect.md](connect.md#webhook-wake). |
| `local` | `mill local` | List the offices on this machine and their aliases. |
| `update` | `mill update [--dry-run]` | Upgrade the mill package (pip), check its SQL (never applies it), restart the wall. Exit 1 with `schema: stale` and the apply command when the book's SQL is not the new pack's. After it: back up the book, A/B, `mill install sql --apply`; recopy skill.md, reload, connect. |
| `install sql` | `mill install sql [--apply]` | Host: does the book hold this pack's SQL (stamp vs pack). `--apply` runs ensure (the one migration entry), then checks; it is the only command that applies SQL to a live book. Exit 1 when it does not match (F66). |

## This machine

| command | form | what |
|---|---|---|
| `route` | `mill route list | add KEY -- PROGRAM | rm KEY` | This desk's HINT redirector chain. See [route.md](route.md). |

## Host setup

| command | form | what |
|---|---|---|
| `install` | `mill install {server,client,book,records,wall,desk,check,cloud,glance-tap} [--apply] [--dry-run] [--http H] [--book B] [--provider P] [--bind B] [--port N] [--dest D] [--lan-only] [--public] [--agent] [--tap T] [--generate [N]] [--link-file PATH]` | server = records + wall (admin); client = mill CLI; check = preflight; cloud = runbook. `--dry-run` mutates nothing. Desks do not run install. See [HOST.md](../install/HOST.md). |
| `uninstall` | `mill uninstall [--apply] [--dest] [--packages] [--dry-run] [--json] [--agent]` | Remove what install placed. |
| `init` | `mill init [--yes] [--host] [--port] [--user] [--password] [--database] [--node] [--bind] [--dashboard-port] [--lan] [--config] [--link-file PATH]` | Write the records config. Pass secrets by prompt, not in shared scripts. The Wall invite link and host seat welcome link it mints go to an owner-only file (`--link-file PATH`, default under `~/.mill/invites`), named as `link_file`; never printed (F64). |
| `wall` | `mill wall [--bind] [--port] [--roots] [--api-only]` | Run the Wall (HTML + `/api` + `/ws`). |
| `wall-check` | `mill wall-check [--base URL] [--filter PROJECT] [--expect-empty]` | Check a running Wall. |
| `wall-src` | `mill wall-src [src] [--apply] [--git-root] [--dest]` | Point the Wall at pip or git source. |
| `score-tick` | `mill score-tick [--once] [--loop] [--every N] [--window N] [--register]` | Scorecard ticker for the host. |
