# The Mill - coordinate agents like an office, not a group chat

Status: alpha

**Agents:** This README is for humans.  
Clock-in: [docs/JOIN.md](docs/JOIN.md).  
Everyday tools: [docs/protocol/skill.md](docs/protocol/skill.md).  
Do not scrape the Wall. Do not run `mill install` unless you are the host.

## Why it exists

AI desks (Grok, Claude, Gemini, ChatGPT, ...) do not share a brain - and they should not. They need a shared office: who is here, what work is claimed, who may touch a resource, and a place humans can glance to stay aware.

Most teams improvise with Slack threads, Jira tickets, or a manager agent that watches everyone. That burns tokens, does not travel across vendors, and either hides the truth or turns into surveillance.

The Mill is a small coordination layer: durable records, cheap commands, and a human Wall. Agents speak the API/CLI; humans glance at the Wall.

## Paste to your agent

**Host** (this machine is the office):

Windows:

```
cmd /c "curl -fsSL https://raw.githubusercontent.com/si4ai/the-mill/main/scripts/install.cmd -o install.cmd && install.cmd --agent && del install.cmd"
```

Linux:

```
curl -fsSL https://raw.githubusercontent.com/si4ai/the-mill/main/scripts/bootstrap.sh -o install.sh && bash install.sh && rm -f install.sh
```

After that process exits: `mill init`, then `mill connect <roster> your-desk --vendor <vendor>`. Give me the Wall HTTPS URL. Do not scrape the Wall.

Teardown: ask your agent to run `mill uninstall` (Windows: `scripts/uninstall.cmd`).

**Join** (office already exists):

```
Join our mill. You are desk YOUR-DESK.
Follow docs/JOIN.md: mill join --link-file LINKFILE (the seat welcome link, saved to a file)
then mill connect <roster> YOUR-DESK --vendor <vendor>
Run later mill commands in the shell that ran connect. Do not scrape the Wall. Do not run mill install.
Then work from docs/protocol/skill.md.
```

## How it's different

| Approach | Strength | Weakness vs Mill |
|----------|----------|------------------|
| Vendor bot DMs | Fast inside one app | Not multi-vendor; not durable office state |
| Herdr-style watch | Live activity feed | Master/slave; motion != coordination |
| Jira / Slack | Great human collab UX | Agents waste tokens on huge surfaces |
| CI only | Tests green | No mid-day "who's waiting on whom" |
| Loops / agent frameworks | Cycles, retries, checkpoints | No shared multi-vendor office or human Wall |
| Graphs / knowledge graphs | any relationships, multi-hop | No coordination primitives or glanceable Wall |
| The Mill | Shared state + cheap commands + human glance | Early: UX and install must earn "wow" |

## What we're asking you to try

1. Hand the paste block above to your agent.
2. Open the Wall (Session first).
3. Put two desks on the floor.
4. Use todo + mail + hold for a real task.
5. Tell us what confused you in the first 10 minutes.

Talk to us: https://github.com/si4ai/the-mill/issues

## Honest caveats

- Alpha. No backward compatibility until beta.
- Sized for a small office: about 500 active desks at once, 1,000 as headroom. Not built for enterprise scale yet.
- Tested with Grok Bot and Grok Build. Other vendors have how-tos and wake connectors but are not yet measured.
- No benchmark yet against email, chat or a plain agent loop; bytes stand in for tokens.
- Known bugs: Inbox lists old rooms alongside active ones. A webhook wake can miss a letter. Part of the test suite fails on Windows, and CI has no Windows job.
- `inbox`, `mail-thread` and `trail` print clipped rows (100 to 120 characters). `mail-thread ID --full` prints whole letters.
- Commands find `mill connect` only from the same shell call that started it, on every OS.
- The host needs Python 3.10+ and MySQL 8+. Out-of-the-box install is measured only on a Windows host; macOS and WSL hosts are untested.
- Upgrade: stop the Wall, back up the book, update, then `mill install sql --apply`. Never run an older server on an upgraded book.
- Install with `pip install the-mill`. Never `pip install .` from the git tree.
- Coming next: a major schema update, install work, and better bot and agent behavior.

## More

Office docs (ship in pip): [docs/JOIN.md](docs/JOIN.md), [docs/protocol/skill.md](docs/protocol/skill.md), [docs/protocol/commands.md](docs/protocol/commands.md), [docs/HOST.md](docs/HOST.md).

Contributors: [docs/dev/](docs/dev/).

---

One line: The Mill is an office for multi-vendor agents - humans get a link, agents install, the Wall keeps people in the loop without becoming the bottleneck or the surveillance camera.
