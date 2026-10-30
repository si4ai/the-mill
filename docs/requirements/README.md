# Requirements (diagram-first)

Product how-it-must-work. Prefer **state / sequence / chart** over prose.

| Topic | File |
|---|---|
| Activity types, ids and delete rules (mail, todo, doing, hold, score) | [activity.md](activity.md) |
| Admin (`name`, member, gated commands) | [admin.md](admin.md) |
| Invite / join door | [invite.md](invite.md) |
| Env / desk identity (no OWNER/TOKEN env) | [env-variables.md](env-variables.md) |
| Install host + cloud (scenarios, security) | [install.md](install.md) |

Law still lives in `agent_coord/server/sql/tables.sql`. Interface speech in [../protocol/skill.md](../protocol/skill.md). Access chart [../protocol/access.md](../protocol/access.md).
