# Mill development docs

Prompts and runbooks for **the-mill maintainers** (git, pack pipeline, PyPI).

Office / customer desks do **not** load this folder. They use:

- [JOIN.md](../JOIN.md) - clock-in + platform split
- [protocol/skill.md](../protocol/skill.md) - mill-desk route map
- [skills/](../skills/) - office-function adapters
- [HOST.md](../HOST.md) - install an office Wall

| Doc | For |
|---|---|
| [AGENTS.md](AGENTS.md) | Repo contributor always-on (tiny) |
| [BUILD.md](BUILD.md) | Pack, pipeline, PyPI, mill update |
| [PROBE-DELETED-ROWS.md](PROBE-DELETED-ROWS.md) | Test-only probe that makes deleted todo and score rows live (#160) |
| [FAILURE-CLASSES.md](FAILURE-CLASSES.md) | Auditor coverage list: who checks which failure class (card 913) |
| [DETERMINISTIC-OFFICE.md](DETERMINISTIC-OFFICE.md) | Design for scripted, self-checking office steps (#282) |
| [OPTIMIZATION.md](OPTIMIZATION.md) | Query and read-path principles, plus the log of optimization examples |
