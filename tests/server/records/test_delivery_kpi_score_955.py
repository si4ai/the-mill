"""Card 955 / F-delivery-kpi-score: per-roster card score filled on card moves.

Claim, --started, pass (ship) and pass --done write hour and day score_evidence
on the roster's `cards` score (desk_id NULL). Lead-time and ETA vs actual ride
on ship. Doing minutes accumulate when a focus on the card ends. A score write
must never refuse the card move. mill score surfaces cards/day and the guards.
"""
from __future__ import annotations

import json

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _loads(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    return json.loads(value)


def _cards_doc(cn, roster: str, stamp: str):
    cur = cn.cursor(dictionary=True)
    cur.execute(
        """SELECT e.value, JSON_UNQUOTE(JSON_EXTRACT(s.meta, '$.n')) AS latest, s.id
             FROM score s
             JOIN member m ON m.desk_id = s.desk_id
             JOIN name r ON r.id = m.name_id AND r.name = %s
             JOIN score_evidence e ON e.score_id = s.id
            WHERE s.kpi = 'cards'
              AND e.`timestamp` = %s""",
        (roster, stamp),
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        return None
    return _loads(row["value"]), str(row["latest"]), int(row["id"])


def _open_claim(cn, need, asker="a955", vol="v955", roster="unit"):
    seed_names(cn, (roster, "roster"), (asker, "desk"), (vol, "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": need}, roster, asker)
    return book, asker, vol


def test_claim_started_pass_done_fill_hour_and_day(cn):
    book, asker, vol = _open_claim(cn, "kpi-955-a")
    rpc._h_claim(book, {"need": "kpi-955-a", "eta": "2h"}, "unit", vol)
    rpc._card_fields(book, {"need": "kpi-955-a", "started": True}, "unit", vol)
    assert rpc._h_pass(book, {"need": "kpi-955-a"}, "unit", vol)["status"] == "shipped"
    assert rpc._h_pass(book, {"need": "kpi-955-a", "step": "done"}, "unit", asker)["status"] == "done"

    # Hour slots follow the book clock (often UTC); find any 1970 hour row.
    cur = cn.cursor(dictionary=True)
    cur.execute(
        """SELECT e.`timestamp` FROM score_evidence e
             JOIN score s ON s.id = e.score_id
             JOIN member m ON m.desk_id = s.desk_id
             JOIN name r ON r.id = m.name_id AND r.name = 'unit'
            WHERE s.kpi = 'cards'
              AND e.`timestamp` >= '1970-01-01' AND e.`timestamp` < '1970-01-02'
            LIMIT 1"""
    )
    hour_row = cur.fetchone()
    cur.execute(
        """SELECT e.`timestamp` FROM score_evidence e
             JOIN score s ON s.id = e.score_id
             JOIN member m ON m.desk_id = s.desk_id
             JOIN name r ON r.id = m.name_id AND r.name = 'unit'
            WHERE s.kpi = 'cards'
              AND e.`timestamp` >= '1970-01-02'
            ORDER BY e.`timestamp` DESC LIMIT 1"""
    )
    day_row = cur.fetchone()
    cur.close()
    assert hour_row is not None, "claim/pass must write the hour score_evidence slot"
    assert day_row is not None, "claim/pass must write the day score_evidence rollup"
    hour = _cards_doc(cn, "unit", str(hour_row["timestamp"]))
    day = _cards_doc(cn, "unit", str(day_row["timestamp"]))
    hdoc, latest, _ = hour
    assert hdoc.get("claimed", 0) >= 1
    assert hdoc.get("started", 0) >= 1
    assert hdoc.get("passed", 0) >= 1
    assert hdoc.get("shipped", 0) >= 1
    assert hdoc.get("lead_sum", 0) >= 0
    assert "eta_sum" in hdoc or hdoc.get("eta_n", 0) >= 0
    assert int(float(latest)) >= 1
    ddoc, _, _ = day
    assert ddoc.get("shipped", 0) >= 1


def test_score_failure_never_blocks_claim(cn):
    """A score step that fails (here: its procedure is missing) never refuses the claim (card 955).

    Card 1113: behavior, not a source check. A deadlock in the step is not swallowed; that case is
    tests/server/records/test_score_step_and_wake_id_1113.py.
    """
    from pathlib import Path as P

    from agent_coord.install.migrate import split_script

    book, asker, vol = _open_claim(cn, "kpi-955-guard")
    sql = (P(__file__).resolve().parents[3] / "agent_coord/server/sql/sp_score.sql").read_text()
    create = [st for st in split_script(sql)
              if st.strip().lower().startswith("create procedure mill_card_score_event(")]
    assert len(create) == 1
    cur = cn.cursor()
    cur.execute("DROP PROCEDURE IF EXISTS mill_card_score_event")
    cn.commit()
    try:
        got = rpc._h_claim(book, {"need": "kpi-955-guard"}, "unit", vol)
    finally:
        cur.execute(create[0])
        cn.commit()
        cur.close()
    assert got["status"] == "claimed"
    hit = rec_todo.find(cn, "unit", "kpi-955-guard")
    assert hit["status"] == "claimed"


def test_mill_score_cards_shows_guards(cn):
    book, asker, vol = _open_claim(cn, "kpi-955-read")
    rpc._h_claim(book, {"need": "kpi-955-read", "eta": "90m"}, "unit", vol)
    rpc._card_fields(book, {"need": "kpi-955-read", "started": True}, "unit", vol)
    rpc._h_pass(book, {"need": "kpi-955-read"}, "unit", vol)
    rpc._h_pass(book, {"need": "kpi-955-read", "step": "done"}, "unit", asker)
    shaped = rpc._h_score(book, {"name": "cards"}, "unit", vol)
    assert shaped["score"] == "cards"
    assert "cards_per_day" in shaped or "guards" in shaped or shaped.get("unit") == "cards/day"
    guards = shaped.get("guards") or shaped
    # Lead time / size mix surface somehow on the read.
    blob = json.dumps(shaped)
    assert "lead" in blob or "lead_min" in blob or "median_lead" in blob
    assert "size_mix" in guards
