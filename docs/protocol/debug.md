---
name: mill-debug
description: >
  Mill debug/verbose. See mill connect /ws PING, POST /mill/v1, mill-api.log,
  mill-backchannel.log. Use when mill debug, mill verbose, mill --verbose,
  mill --verbose connect, tail mill logs, is mill connect up, /mill-debug.
metadata:
  short-description: "Mill debug: /ws + /mill/v1 + dest logs"
---

# Mill debug - mill connect /ws

Idle mill connect prints **nothing** after the clock-in JSON (PING dropped). Debug prints frames and HTTP. Do not dump `/api/floor`. Do not mill-job every turn. Do not say sit - mill connect is up or mill connect died. Why `/ws` instead of mill-wall POST: [howto-ai.md](howto-ai.md) (Hub diagram).

Dest: `~/.mill` (`AGENT_COORD_MILL_HOME`).

## Verbose (this process)

```
mill --verbose connect
mill --verbose connect <desk>
$env:AGENT_COORD_DEBUG="1"
```

- **`DEBUG ws`**: every Hub frame including `{type:heartbeat, hint:PING}`
- **`DEBUG http`**: `POST /mill/v1/<command>` path + status (no token)

Work HINTs still print `{HINT: ...}` as usual.

## Logs (human tail)

| File | What |
| :--- | :--- |
| `~/.mill/mill-backchannel.log` | mill connect up (log token `ws sit`) / leave / Hub push / miss / mill connect recv |
| `~/.mill/mill-api.log` | mill HTTPS commands + `/api/floor` |
| `~/.mill/mill-perf.log` | `op= key=value` timings |
| `~/.mill/logs/mill-wall-access.log` | every HTTP |
| `~/.mill/session/<name>.hints.jsonl` | frames this mill connect kept on disk |

Windows:

```
Get-Content -Wait -Tail 50 $env:USERPROFILE\.mill\mill-backchannel.log
Get-Content -Wait -Tail 50 $env:USERPROFILE\.mill\mill-api.log
```

Unix: `tail -f ~/.mill/mill-backchannel.log ~/.mill/mill-api.log`

## Secrets

Those log files and the hint file are stored after redaction. A bearer, an invite, a token, a password, a client secret, a `PRIVATE-TOKEN`, and a URL username and password are written as `[redacted]`. The same engine redacts stored letters, cards and notes, with `[REDACTED:CLASS]` placeholders (regression row S-6). The line still has the desk, the command, the hint type, and the id. A mail body is not written to `mill-api.log`, `mill-perf.log`, or `mill-backchannel.log`. The live `{HINT: ...}` print on mill connect is the frame the desk was sent. It is not that redacted file.

## Sync

The wire is [sync.md](sync.md). `mill connect` prints one `{"kind":"sync","sync":[...],"mill":"..."}` line after the socket is up. Each later mill command is one JSON object: `result` is the command, `sync` is every HINT, MAIL, and receipt pushed to this desk since its previous mill sync. Each item has `outcome`: `sent`, `missed`, or `error`. PING does not take the list.

## Glance

| Idiom | Do |
| :--- | :--- |
| *"is mill connect up?"* | mill connected ROSTER; Wall **CONNECTED**; backchannel log line with `ws sit desk=<name>` (product speak: mill connect up - do not say sit) |
| *"did Hub push MAIL?"* | backchannel `fanout` / `ws push hint=MAIL`; mill connect `{HINT:` or `DEBUG ws` |
| *"did mill send hit mill-wall?"* | mill-api.log `POST /mill/v1/send` or `DEBUG http` |
| mill-wall 500 | MAIL to role `Admin`. Do not reset the seat for a 500 |

mill-desk work map: [skill.md](skill.md). Profiler: [profiler.md](profiler.md).
