"""Floor trees and watchers are glance lists. No hint body, no hex plan label."""

from agent_coord.server.records.floor import _filter_tree_nodes, _name_catalog, _tree_face
from agent_coord.server.records.tree import pack_trees
from agent_coord.server.records.watcher import group_watchers, pack_watchers


def test_pack_trees_hides_minted_hex_and_indents() -> None:
    rows = [
        {
            "tree": "ab12cd34ef",
            "type": "todo",
            "id": 1,
            "lft": 1,
            "rgt": 4,
            "roster_id": "the-mill",
            "title": "parent",
            "status": "open",
            "who": "",
        },
        {
            "tree": "ab12cd34ef",
            "type": "todo",
            "id": 2,
            "lft": 2,
            "rgt": 3,
            "roster_id": "the-mill",
            "title": "child",
            "status": "claimed",
            "who": "builder",
        },
        {
            "tree": "release",
            "type": "todo",
            "id": 3,
            "lft": 1,
            "rgt": 2,
            "roster_id": "the-mill",
            "title": "cut",
            "status": "open",
            "who": "",
        },
    ]
    out = pack_trees(rows)
    assert out[0]["hidden"] is True
    assert out[0]["nodes"][0]["depth"] == 0
    assert out[0]["nodes"][1]["depth"] == 1
    assert out[1]["hidden"] is False
    assert out[1]["name"] == "release"


def test_pack_watchers_flag_only() -> None:
    rows = pack_watchers(
        [
            {
                "type": "todo",
                "id": 5,
                "desk": "builder",
                "custom": 1,
                "roster_id": "the-mill",
                "title": "parent",
                "status": "open",
            },
            {
                "type": "mail",
                "id": 9,
                "desk": "presence",
                "custom": 0,
                "roster_id": "the-mill",
                "title": "note",
                "status": "mail",
            },
        ]
    )
    assert rows[0]["hint"] == "custom"
    assert rows[1]["hint"] == "default"
    assert "endpoint_url" not in rows[0]
    assert "body" not in rows[1]
    grouped = group_watchers(rows + [{"type": "score", "id": 1, "desk": "validator", "hint": "default", "roster_id": "Office", "title": "ticks", "status": "score"}])
    assert len(grouped) == 3
    assert grouped[0]["desks"][0] == {"desk": "builder", "hint": "custom"}
    assert grouped[2]["type"] == "score"
    assert grouped[2]["title"] == "ticks"


def test_catalog_is_every_name_and_hides_minted_trees() -> None:
    rows = _name_catalog([
        {"name_type": "project", "name": "Office"},
        {"name_type": "desk", "name": "builder"},
        {"name_type": "role", "name": "Admin"},
        {"name_type": "label", "name": "bug"},
        {"name_type": "res", "name": "board.html"},
        {"name_type": "tree", "name": "release"},
        {"name_type": "tree", "name": "ab12cd34ef"},
        {"name_type": "other", "name": "mill-wall.ticks"},
    ])
    got = {(r["kind"], r["name"]) for r in rows if not r.get("hidden")}
    assert ("project", "Office") in got
    assert ("desk", "builder") in got
    assert ("role", "Admin") in got
    assert ("label", "bug") in got
    assert ("res", "board.html") in got
    assert ("tree", "release") in got
    assert ("other", "mill-wall.ticks") in got
    assert all("ab12cd34ef" not in r["name"] for r in rows)
    hidden = [r for r in rows if r.get("hidden")]
    assert hidden == [{"kind": "tree", "name": "", "n": 1, "hidden": True}]


def test_tree_face_labels_every_activity_type() -> None:
    assert _tree_face("todo", {"id": 5}, {"title": "parent", "status": "open", "who": "builder"}) == (
        "parent",
        "open",
        "builder",
    )
    assert _tree_face(
        "todo",
        {"id": 5, "todo_status": "claimed", "todo_body": '{"doing":"nest"}'},
        {"title": "board", "status": "open", "who": "builder"},
    ) == ("nest", "claimed", "builder")
    assert _tree_face("mail", {"id": 9}, {"title": "note", "status": "mail", "who": "presence"})[0] == "note"
    assert _tree_face("doing", {"id": 3, "join_desk": "builder", "join_doing": "present"}, {}) == (
        "builder | present",
        "doing",
        "",
    )
    assert _tree_face("hold", {"id": 4, "hold_resource": "board.html", "hold_desk": "builder"}, {}) == (
        "board.html",
        "hold",
        "builder",
    )
    assert _tree_face("score", {"id": 7, "score_kpi": "mill-wall.ticks", "score_desk": "validator"}, {}) == (
        "mill-wall.ticks",
        "score",
        "validator",
    )
    assert _tree_face("name", {"id": 1}, {"title": "Office", "status": "name", "who": ""})[0] == "Office"


def test_filter_tree_keeps_ancestor() -> None:
    nodes = [
        {"type": "todo", "id": 1, "lft": 1, "rgt": 4, "roster_id": "other", "depth": 0},
        {"type": "todo", "id": 2, "lft": 2, "rgt": 3, "roster_id": "the-mill", "depth": 1},
    ]
    kept = _filter_tree_nodes(nodes, {"the-mill"})
    assert [n["id"] for n in kept] == [1, 2]
    assert kept[1]["depth"] == 1
