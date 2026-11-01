# Install - host & cloud (howto)

Product how-to for putting an office on a machine. **Requirements / must-work:** [../requirements/install.md](../requirements/install.md). Desk join (no MySQL): [../JOIN.md](../JOIN.md).

| Doc | What |
|---|---|
| [HOST.md](HOST.md) | Local / any-OS host: `mill install server`, update a live office, and [mill-wall + MySQL Operator config](HOST.md#mill-wall-and-mysql-operator-config) |
| [MAC-TEST-DAY.md](MAC-TEST-DAY.md) | One-day macOS rental checklist (card 933); fill before booking the host |
| [CLOUD.md](CLOUD.md) | Workstation journey onto one cloud VM |
| [cloud/aws.md](cloud/aws.md) | AWS playbook (status in the file) |
| [cloud/azure.md](cloud/azure.md) | Azure playbook (status in the file) |
| [cloud/gcp.md](cloud/gcp.md) | GCP playbook (status in the file) |
| [cloud/self.md](cloud/self.md) | Generic Linux VM playbook (status in the file) |
| [../JOIN.md](../JOIN.md) | Desk/client join (pip + mill join) |

## Choices & preconditions

```mermaid
flowchart TD
  start([Need an office]) --> who{Who needs Wall / join?}
  who -->|Just me + my agents on this PC| solo[Solo local host]
  who -->|Team / remotes / vendor / laptop sleeps| cloudish[Dedicated or cloud host]

  solo --> preL{Preconditions}
  preL --> p1[Python 3.10+]
  preL --> p2[Admin/sudo for 443 + MySQL]
  preL --> p3[No cloud account required]
  p1 --> localInst[pip install the-mill]
  p2 --> localInst
  p3 --> localInst
  localInst --> localRun["mill install server --apply\nmill init --yes"]
  localRun --> doorL{Door}
  doorL -->|LAN only| lan[door=ip / wall-allow CIDRs]
  doorL -->|Off-LAN later| invL[mill invite mint/enable]
  lan --> wallL[Wall https://127.0.0.1/]
  invL --> wallL
  wallL --> desksL[Desks: mill join + mill connect]

  cloudish --> preC{Preconditions}
  preC --> c1[Cloud account AWS/Azure/GCP]
  preC --> c2[VM with 443 - console or your CLI]
  preC --> c3[Cloud keys NEVER in mill]
  preC --> c4[SSH/RDP you can lock]
  c1 --> cloudInst
  c2 --> cloudInst
  c3 --> cloudInst
  c4 --> cloudInst
  cloudInst[pip install the-mill on VM]
  cloudInst --> cloudRun["mill install server --apply --public\nmill init --yes"]
  cloudRun --> doorC[Invite door default]
  doorC --> wallC[Wall https://dns-or-ip/]
  wallC --> desksC[Desks join invite URL]

  solo -.-> sec[Max-security bar]
  cloudish -.-> sec
  sec --> s1[MySQL not on public net]
  sec --> s2[HTTPS Wall only]
  sec --> s3[Bearer / invite hygiene]
  sec --> s4[Tokens in session files not env]
```

## Two roles (unchanged)

| Role | Runs | Command spine |
|---|---|---|
| **Host** | MySQL + mill-wall | `mill install server --apply` -> `mill init` |
| **Join** | mill CLI only | `mill join https://.../` -> `mill connect` |
