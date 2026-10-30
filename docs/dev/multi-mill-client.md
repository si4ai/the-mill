# Multi-mill client (review)

Status: **for review**. Not the agent manual. Public wording in `docs/JOIN.md` and `docs/protocol/skill.md` stays with Mill Prompt Gardener.

One workstation can be a client of more than one mill. Each mill is one host directory. An office name is a local alias for that host. The alias is not sent to the Wall and is not stored in the book.

## Layout

```
.mill/
  active                          # last alias, for example Offsite
  alias/
    Offsite                       # 203.0.113.10
    lan                           # 198.51.100.10
  203.0.113.10/
    ca.crt
    url                           # https://203.0.113.10
    active                        # last desk on this host
    DESK_build-cloud/
      token                       # bearer token, mode 0600
  198.51.100.10/
    ca.crt
    url
    active
    DESK_gardener/
      token
```

The host key is a DNS name or an IP from the invite URL. Port 443 is omitted. Any other port is `host:port`. A DNS name is kept when it resolves to an IP already used for that office. The wall comes from the join link, stored under `--office <alias>`; connect takes no host. A single other positional is the desk, not the project: `mill connect <desk>` uses the project stored at join, or exits 1 with `connect: project required`. `mill connect the-mill build-app` is still project then desk. `the-mill` is not a host.

The CA is once per host. The token file holds the bearer token. The book stores the SHA-256 of that token. With an office or host selected, that desk's route, want, spawn, grok-session, and hint log sit in the desk directory. With no office selected they stay in `session/`.

## Commands

Command names do not change. `--office <alias>` may appear before or after the command.

| Command | What it uses |
|---|---|
| `mill <command> --office Offsite` | alias `Offsite`, then that host |
| `mill <command>` | `.mill/active` when that file exists |
| no `--owner` | `.mill/<host>/active` |
| `--owner` | that desk, and it updates `.mill/<host>/active` |

`mill join --link-file LINKFILE --office Offsite` writes the alias, `ca.crt`, and `url` under the host. It does not change the legacy `config.toml` `mill_url`.

`mill connect --office Offsite` sets `.mill/active` to that alias and opens one websocket to that Wall. If that host has no token file yet, connect copies the token this machine already holds for that desk out of `session/`. It does not ask the Wall for a second token.

On the wire the call is still `POST /mill/v1/<command>` with that desk's bearer token. The office name is not in the body.

## Legacy

If `.mill/active` does not exist and `--office` is omitted, the client keeps the single-office layout: `config.toml` `mill_url`, `session/<desk>.token`, and `session/active`. A machine that has not used `--office` is unchanged.

## Human phrase

"Check my todos on Offsite" resolves the alias, then reads that desk's todos on that Wall only.
