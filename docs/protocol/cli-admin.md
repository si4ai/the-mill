# mill CLI: admin

Part of the mill CLI (command line interface). This page lists the commands for members, seats, names and trust. Daily desk commands are in [cli-desk.md](cli-desk.md). Join and host setup are in [cli-install.md](cli-install.md). Trust chart: [admin.md](../requirements/admin.md) (repo only).

Every command takes `--office ALIAS` (before or after the command) and `-h`. Trust is high by default (any seated desk may mint names and seats); limited means Admin only. Always Admin, either trust: invite keys, rename, retire, reclaim, reset, setting trust.

## Members

| command | form | what |
|---|---|---|
| `member` | `mill member` | List memberships. |
| `add` | `mill add roster <name> [d1,d2]` | Add desks (comma list; omitted = this desk) to a roster. Self always; another desk is trust-gated. Roster Admin grant is host loopback only. |
| `remove` | `mill remove roster <name> [d1,d2] [--yes]` | Take desks off a roster. Asks y/N. |

`add room` / `remove room` are not wired yet: rooms have no member list (reply in a room to join it).

## Seats and invites

| command | form | what |
|---|---|---|
| `invite` | `mill invite --seat DESK [--roster R] [--link-file PATH | --print-link]` | Mint a one-seat welcome link for a desk. `--roster` defaults to the desk's one non-Office roster. Trust-gated. The link carries the seat secret, so it is written to an owner-only file (`~/.mill/invites/DESK-<UTC stamp>.link`, file 0600, folder 0700) and the reply names it as `link_file`; `--link-file PATH` picks the file (an existing file is refused), `--print-link` prints the link on stdout instead. `--mint` and `--rotate` write the invite-key link the same way. The printed reply never carries the secret in any field, `join_argv` included (F64). |
| | `mill invite --mint [--label L] [--ttl T]` / `--enable KEY` / `--list` / `--revoke KEY` / `--ttl T --for KEY` | Human Wall invite keys. Admin. |
| | `mill invite --door path|ip|invite` / `--rotate` / `--lan-only on|off` / `--join KEY --party human|agent [party_id]` | Door mode, token rotation, LAN bind, record a join. Admin. |
| `reset` | `mill reset seat <desk> [--yes]` / `mill reset --dead` | Admin: clear a lost seat token so the desk can join again (a seat is per desk); also frees its holds and ends its doing. Asks y/N. `--dead` counts tokenless seats; deletes nothing. |

## Names

| command | form | what |
|---|---|---|
| `create` | `mill create roster <name> [--yes]` / `mill create label <name> [--yes]` | Create a name. Asks y/N; the name is typed once. |
| `rename` | `mill rename <roster|label|desk> <old> <new> [--yes]` | Admin (or desk self-rename). Retype the new name at the prompt. The reserved Admin roster keeps its name; Office may be renamed and stays reachable as Office (F92). |
| `retire` | `mill retire <roster|label|desk> <name> [--yes]` | Admin (a desk may retire itself): soft delete. Retype the name at the prompt. `mill retire score <roster> <name>` is the desk form for a score (cli-desk.md). |
| `reclaim` | `mill reclaim <roster|label|desk> <name> [--yes]` | Admin: undelete a retired name. Asks y/N. |

## Trust

| command | form | what |
|---|---|---|
| `trust` | `mill trust [high|limited]` | Show trust (any seated desk); set it (Admin). |
