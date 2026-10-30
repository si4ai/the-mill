# Tree - prompt for **wall-ui-desk** (wall_ui)

**Ingest only.** Do not mill-job mill-wall, `server/records/`, or `server/sql/`. You are **wall-desk**. Files: `agent_coord/web/wall_ui/**` only. mill hold those files. **presence-desk** owns mill-wall commands and `mill_tree_*` SPs.

Tree is **structure**. A plan is a tree name (bare). A hidden plan is 10 hex. Do not paint that hex as a product name unless the same card sits on **two** named plans.

## Book (do not change)

```sql
-- name_id = tree name (name.type = tree, bare name). Payload = activity (type, id).
-- The first card is lft 1, rgt 2. Naming the plan does not insert a node.
PRIMARY KEY (name_id, type, id)
UNIQUE (name_id, lft), UNIQUE (name_id, rgt)
KEY (type, id)
```

Celko nested set: **one SELECT**, no walk.

- Whole plan: `ORDER BY lft` for that `name_id`.
- Branch: `lft BETWEEN parent.lft AND parent.rgt`.
- Ancestors (fanout): `anc.lft <= node.lft AND anc.rgt >= node.rgt` (same `name_id`).

Same activity **may** sit on more than one plan. Within one plan, once (a tree, not a DAG).

## Operators (speech -> mill; Wall does not invent commands)

| Human | Mill | SP |
|---|---|---|
| put that **under** that / attach that **below** that | `attach` parent then child `{type_a,id_a,type_b,id_b}` | `mill_tree_add` |
| **move** that under that | `move` `{type,id,parent_type,parent_id}` | `mill_tree_move` |
| kill that **branch** | `prune` `{type,id}` | `mill_tree_prune` |
| take off the plan, **keep children** | `detach` `{type,id}` | `mill_tree_remove` |

mill **auto-mints** a 10-hex tree name if the parent is on 0 or 1 plan. If the card is on **two** plans, mill fails closed with `which TREE_* (activity is on more than one plan)` until `{tree: project-a-plan}`.

**Wall:** drag under calls `attach` or `move`. `attach` is `mill_tree_add`. The plan name stays off the glass.

## Glance (WOW)

At a glance the human sees the **outline** (indent = ancestors), not a name list.

- Indent from nested-set: for each row in `ORDER BY lft`, depth = how many rows have `lft < this.lft AND rgt > this.rgt` (same `name_id`).
- Paint the **payload** (todo title/status, mail, ...), not `name_id`.
- If a todo is on **one** hidden tree: one outline, no plan picker.
- If on **two named** plans: show the plan names, not the 10-hex hidden name.
- TODO kanban (parked/open/claimed) can stay; **also** show parent/child (the plan). Flat kanban alone hides order.

## Data (ask presence-desk if missing)

Wall parts are `GET /api/v1/<part>` with one of `?project=`, `?role=`, or `?lan=`. Do **not** invent REST `GET /mill/v1/tree/...`. mill-wall commands are `POST /mill/v1/<command>`. A plan in that JSON looks like:

```json
"trees": [
  {
    "name": "project-a-plan",
    "hidden": false,
    "nodes": [
      {"type": "todo", "id": 5, "lft": 1, "rgt": 4, "depth": 0, "title": "...", "status": "open"},
      {"type": "todo", "id": 6, "lft": 2, "rgt": 3, "depth": 1, "title": "...", "status": "open"}
    ]
  }
]
```

`hidden: true` when the plan name is 10 hex (do not label the plan). Depth may be computed in wall_ui from `lft`/`rgt` if the payload omits it.

## Cheap / do not

- Do not dump the whole DFS into an **agent** chat. Wall **may** paint the plan (human glance).
- Do not mill-job mill-wall or edit `server/sql/` / `server/records/`.
- Do not restore `attach` table. mill attach = put under.
- HINT stays small (`TODO`/`NAME` on ancestors). Wall reads `GET /api/v1/<part>`.

## Measure (loop 3)

Can a human see **who / plan / progress** without asking an agent? Empty outline when dest has `tree` rows = glance failed. mill send dest=desk (`presence-desk`) if floor has no `trees` yet.
