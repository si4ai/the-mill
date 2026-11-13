/* PRIORITIES tab (card 1153, first slice): each desk's ranked list, as its connect focus line sees it.
 * Design: letters 5553 (ask), 5556 gardener, 5558 builder, 5559 auditor, 5566 validator.
 * - A desk's list is the todo label named after the desk (mill label todo <id> <desk> --ord N),
 *   the same source as the connect focus line and todo --mine (client/focus.py).
 * - One column per desk, top FOCUS_TOP workable cards: not done, not parked, not held by another
 *   desk; ord ascending (0 pinned, 65535 unplaced), ties by card id. Same rule as focus.order_mine.
 * - Checks are visible facts, never blocks: "no focus line" (with cause and fix), human list vs desk
 *   list conflict, tied ranks on the shared human list, #0 card with no recent activity.
 * - human-priorities is shown as an unowned shared list until device-link identity (card 1101).
 * - Every trusted viewer sees every list. Fields the server does not send are left out, never guessed.
 * Data contract (asked of Loop 2 on card 1153): GET /api/v1/labels?project=Office&limit=500 ->
 *   { rows: [{ label, type, id, ord, updated?, card?: { roster, need, status, volunteer, eta_at?,
 *     progress?, needs_human?, last_activity_at?, last_activity_kind?, tw_ms? } }], next }.
 * A server without the route paints "unavailable". window._prioritiesCtx is a sample/test override. */
(function (global) {
  "use strict";
  var FOCUS_TOP = 5;
  var UNPLACED = 65535;
  var HUMAN_LIST = "human-priorities";
  var HUMAN_TOP = 3;
  var HUMAN_SHOWN = 10;
  var DRIFT_DAYS = 3;
  var DAY_MS = 86400000;
  var DASH = "\u2014";

  function h(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function int(v, dflt) {
    var n = parseInt(v, 10);
    return Number.isFinite(n) ? n : dflt;
  }
  function parseLocal(raw) {
    /* Naive office-local "YYYY-MM-DD HH:MM:SS[.ffffff]", read on the viewer's clock (as the SCORE tab). */
    if (raw == null || raw === "") return null;
    var t = Date.parse(String(raw).replace(" ", "T"));
    return Number.isFinite(t) ? t : null;
  }
  function ago(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    var m = Math.max(0, Math.round(ms / 60000));
    if (m < 60) return m + "m";
    var hr = Math.round(m / 60);
    if (hr < 48) return hr + "h";
    return Math.floor(ms / DAY_MS) + "d";
  }
  function has(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k) && o[k] != null && o[k] !== ""; }

  /* ---- Focus rule, mirrored from client/focus.py (tests/wall/test_wall_priorities.py holds both to one fixture). */
  function prioRank(rows, label) {
    /* (todo id, ord) wearing label, ord ascending, ties by card id (focus._rank_rows). */
    var out = [];
    (rows || []).forEach(function (r) {
      if (!r || r.type !== "todo" || String(r.label || "") !== label) return;
      var id = int(r.id, null);
      if (id == null) return;
      out.push([id, int(r.ord, 0)]);
    });
    out.sort(function (a, b) { return (a[1] - b[1]) || (a[0] - b[0]); });
    return out;
  }
  function prioActionable(card, desk) {
    /* focus.actionable: not done, not parked, not held by another desk. */
    var st = String((card && card.status) || "");
    if (st === "done" || st === "parked") return false;
    var vol = String((card && card.volunteer) || "");
    return vol === "" || vol === desk;
  }
  function prioFocusCards(cards, desk, rank) {
    /* focus.order_mine, focus part only: cards wearing label desk and actionable, by (ord, id). */
    var ords = {};
    (rank || []).forEach(function (t) { ords[t[0]] = t[1]; });
    var focus = [];
    (cards || []).forEach(function (c) {
      if (!c) return;
      var labels = Array.isArray(c.labels) ? c.labels : [];
      if (labels.indexOf(desk) < 0 || !prioActionable(c, desk)) return;
      var id = int(c.id, 0);
      var o = Object.prototype.hasOwnProperty.call(ords, id) ? ords[id] : UNPLACED;
      focus.push({ o: o, id: id, card: Object.assign({}, c, { focus: o }) });
    });
    focus.sort(function (a, b) { return (a.o - b.o) || (a.id - b.id); });
    return focus.map(function (f) { return f.card; });
  }
  function prioFocusTop(cards, desk, rank) {
    return prioFocusCards(cards, desk, rank).slice(0, FOCUS_TOP);
  }

  /* ---- Route rows -> board cards (each card wears every label it has a row on). */
  function prioCards(rows) {
    var byId = {}, order = [];
    (rows || []).forEach(function (r) {
      if (!r || r.type !== "todo" || !r.card) return;
      var id = int(r.id, null);
      if (id == null) return;
      if (!byId[id]) {
        byId[id] = Object.assign({}, r.card, { id: id, labels: [] });
        order.push(id);
      }
      var lab = String(r.label || "");
      if (lab && byId[id].labels.indexOf(lab) < 0) byId[id].labels.push(lab);
    });
    return order.map(function (id) { return byId[id]; });
  }
  function title(card) {
    var need = String((card && card.need) || "").trim();
    return need.split("\n")[0].slice(0, 90);
  }

  /* ---- Model. Pure: ctx { rows (null = route missing), desks (seated desk names), now } in. */
  function prioModel(ctx) {
    ctx = ctx || {};
    var now = ctx.now == null ? Date.now() : ctx.now;
    var rows = Array.isArray(ctx.rows) ? ctx.rows : null;
    if (!rows) return { available: false, now: now, columns: [], human: null, served: {} };
    var cards = prioCards(rows);
    var byId = {};
    cards.forEach(function (c) { byId[c.id] = c; });
    var served = {
      updated: rows.some(function (r) { return r && has(r, "updated"); }),
      eta_at: cards.some(function (c) { return has(c, "eta_at"); }),
      needs_human: cards.some(function (c) { return Object.prototype.hasOwnProperty.call(c, "needs_human"); }),
      last_activity_at: cards.some(function (c) { return has(c, "last_activity_at"); }),
      progress: cards.some(function (c) { return has(c, "progress"); }),
      tw_ms: cards.some(function (c) { return has(c, "tw_ms"); })
    };

    /* Shared human list: every row (todo and mail) by ord, ties by id; done cards counted, not listed. */
    var hRows = rows.filter(function (r) { return r && String(r.label || "") === HUMAN_LIST; }).map(function (r) {
      return { type: r.type, id: int(r.id, 0), ord: int(r.ord, 0), card: r.type === "todo" ? byId[int(r.id, 0)] || null : null, updated: r.updated };
    }).sort(function (a, b) { return (a.ord - b.ord) || (a.id - b.id); });
    var hOpen = hRows.filter(function (r) { return !(r.card && r.card.status === "done"); });
    var ties = [];
    var byOrd = {};
    hOpen.forEach(function (r) {
      if (r.ord === UNPLACED) return;
      (byOrd[r.ord] = byOrd[r.ord] || []).push(r.id);
    });
    Object.keys(byOrd).map(Number).sort(function (a, b) { return a - b; }).forEach(function (o) {
      if (byOrd[o].length > 1) ties.push({ ord: o, ids: byOrd[o] });
    });
    var hTop = hOpen.filter(function (r) { return r.type === "todo" && r.card; }).slice(0, HUMAN_TOP);
    var human = {
      label: HUMAN_LIST,
      present: hRows.length > 0,
      rows: hOpen.slice(0, HUMAN_SHOWN),
      more: Math.max(0, hOpen.length - HUMAN_SHOWN),
      done: hRows.length - hOpen.length,
      unplaced: hOpen.filter(function (r) { return r.ord === UNPLACED; }).length,
      ties: ties,
      top: hTop,
      noDesk: [],
      rerankedAt: newest(hRows)
    };

    /* Desks: every desk-named list, every seated desk, and the holder of each human top card. */
    var desks = {};
    rows.forEach(function (r) {
      var lab = String((r && r.label) || "");
      if (lab && lab !== HUMAN_LIST) desks[lab] = 1;
    });
    (ctx.desks || []).forEach(function (d) { if (d) desks[String(d)] = 1; });
    hTop.forEach(function (r) {
      var vol = String(r.card.volunteer || "");
      if (vol) desks[vol] = 1;
      else human.noDesk.push({ id: r.id, ord: r.ord });
    });

    var columns = Object.keys(desks).sort().map(function (desk) {
      var rank = prioRank(rows, desk);
      var focus = prioFocusCards(cards, desk, rank);
      var top = focus.slice(0, FOCUS_TOP);
      var mine = rank.map(function (t) { return byId[t[0]]; }).filter(Boolean);
      var onBoard = mine.filter(function (c) { return c.status !== "done"; });
      var parked = onBoard.filter(function (c) { return c.status === "parked"; }).length;
      var held = onBoard.filter(function (c) { return c.status !== "parked" && !prioActionable(c, desk); });
      var col = {
        desk: desk,
        top: top.map(function (c, i) { return rowOf(c, i, now); }),
        ranked: onBoard.length,
        more: Math.max(0, focus.length - FOCUS_TOP),
        parked: parked,
        held: held.length,
        heldBy: held.map(function (c) { return String(c.volunteer || ""); }).filter(function (v, i, a) { return v && a.indexOf(v) === i; }),
        empty: null,
        rerankedAt: newest(rows.filter(function (r) { return r && String(r.label || "") === desk; })),
        drift: null,
        conflicts: []
      };
      if (!top.length) col.empty = emptyFact(desk, col);
      if (top.length && served.last_activity_at) {
        var t0 = parseLocal(top[0].last_activity_at);
        var age = t0 == null ? null : now - t0;
        if (age == null || age >= DRIFT_DAYS * DAY_MS) {
          col.drift = { id: top[0].id, days: age == null ? null : Math.floor(age / DAY_MS) };
        }
      }
      hTop.forEach(function (r) {
        if (String(r.card.volunteer || "") !== desk) return;
        if (top.some(function (c) { return int(c.id, 0) === r.id; })) return;
        var pos = -1;
        focus.forEach(function (c, i) { if (pos < 0 && int(c.id, 0) === r.id) pos = i; });
        var where;
        if (pos >= 0) where = "position " + (pos + 1) + " on this list";
        else if (r.card.status === "parked") where = "parked";
        else if ((r.card.labels || []).indexOf(desk) < 0) where = "not on this desk's list";
        else where = "not workable here";
        col.conflicts.push({ id: r.id, ord: r.ord, where: where });
      });
      return col;
    });
    return { available: true, now: now, columns: columns, human: human, served: served };
  }
  function newest(rs) {
    var best = null;
    (rs || []).forEach(function (r) {
      var t = parseLocal(r && r.updated);
      if (t != null && (best == null || t > best)) best = t;
    });
    return best;
  }
  function rowOf(c, i, now) {
    var r = {
      pos: i + 1, id: int(c.id, 0), ord: int(c.focus, UNPLACED), title: title(c),
      status: String(c.status || ""), needsYou: c.needs_human === true, eta: null, overdue: null,
      progress: has(c, "progress") ? String(c.progress) : null,
      twMs: has(c, "tw_ms") && Number.isFinite(Number(c.tw_ms)) ? Number(c.tw_ms) : null,
      last_activity_at: c.last_activity_at || null,
      last_activity_kind: c.last_activity_kind || null
    };
    if (has(c, "eta_at")) {
      r.eta = String(c.eta_at);
      var t = parseLocal(c.eta_at);
      if (t != null && t < now && r.status !== "shipped" && r.status !== "done") r.overdue = ago(now - t);
    }
    return r;
  }
  function emptyFact(desk, col) {
    var why;
    if (!col.ranked) why = "0 ranked";
    else if (col.parked === col.ranked) why = col.ranked + " ranked, all parked";
    else if (!col.parked) why = col.ranked + " ranked, all held by " + col.heldBy.join(", ");
    else why = col.ranked + " ranked, all parked or held (" + col.parked + " parked, " + col.held + " held by " + col.heldBy.join(", ") + ")";
    return { why: why, fix: "mill label todo <id> " + desk + " --ord 0" };
  }

  /* ---- HTML. */
  function ordTxt(o) { return o === UNPLACED ? "u" : "#" + o; }
  function cardRow(r, served) {
    var dim = [];
    if (r.progress != null) dim.push('<span class="prio-dim" title="progress (card meta)">' + h(r.progress) + "</span>");
    if (r.twMs != null) dim.push('<span class="prio-dim" title="tw doing time on this card">tw ' + h(fmtMs(r.twMs)) + "</span>");
    /* ETA: a dash when the server sends ETAs but this card has none; left out when no card carries one. */
    var eta = !served.eta_at ? "" : r.eta == null ? '<span class="prio-eta">ETA ' + DASH + "</span>"
      : '<span class="prio-eta' + (r.overdue ? " overdue" : "") + '" title="ETA ' + h(r.eta) + '">' +
        (r.overdue ? "overdue " + h(r.overdue) : "ETA " + h(r.eta.slice(5, 16))) + "</span>";
    return '<li class="prio-row" data-prio-card="' + r.id + '">' +
      '<span class="prio-ord" title="ord on this desk\'s list">' + h(ordTxt(r.ord)) + "</span>" +
      '<span class="prio-card"><b>' + r.id + "</b> " + h(r.title || DASH) + "</span>" +
      '<span class="prio-st st-' + h(r.status) + '">' + h(r.status) + "</span>" +
      (r.needsYou ? '<span class="prio-you">needs you</span>' : "") +
      eta + (dim.length ? '<span class="prio-dims">' + dim.join(" ") + "</span>" : "") +
      "</li>";
  }
  function fmtMs(ms) {
    var m = Math.round(ms / 60000);
    return m < 60 ? m + "m" : Math.floor(m / 60) + "h " + (m % 60) + "m";
  }
  function deskCol(c, m) {
    var head = '<header class="prio-head"><h3>' + h(c.desk) + "</h3>" +
      '<span class="prio-meta">' + c.ranked + " ranked" + (c.parked ? " \u00b7 " + c.parked + " parked" : "") + "</span></header>";
    var facts = [];
    if (c.rerankedAt != null) facts.push('<span class="prio-fact">re-ranked ' + ago(m.now - c.rerankedAt) + " ago</span>");
    if (c.drift) facts.push('<span class="prio-fact warn">ranked #0, no activity ' + (c.drift.days == null ? "on record" : c.drift.days + "d") + "</span>");
    var body = c.empty
      ? '<p class="prio-nofocus" data-prio-check="no-focus">No focus line: ' + h(c.empty.why) +
        '. Rank a workable card: <code>' + h(c.empty.fix) + "</code></p>"
      : '<ol class="prio-list">' + c.top.map(function (r) { return cardRow(r, m.served); }).join("") + "</ol>";
    var checks = c.conflicts.map(function (x) {
      return '<p class="prio-conflict" data-prio-check="conflict">' + HUMAN_LIST + " " + ordTxt(x.ord) +
        ": card " + x.id + " is not in this desk's top " + FOCUS_TOP + " (" + h(x.where) + ")</p>";
    }).join("");
    var foot = [];
    if (c.more) foot.push("+" + c.more + " more workable");
    if (c.held) foot.push(c.held + " held by " + h(c.heldBy.join(", ")));
    return '<section class="prio-col' + (c.empty ? " is-empty" : "") + (c.conflicts.length ? " has-conflict" : "") +
      '" data-prio-desk="' + h(c.desk) + '">' + head +
      (facts.length ? '<div class="prio-facts">' + facts.join("") + "</div>" : "") + checks + body +
      (foot.length ? '<footer class="prio-foot">' + foot.join(" \u00b7 ") + " (not shown to the desk)</footer>" : "") +
      "</section>";
  }
  function humanCol(hm, m) {
    if (!hm.present) {
      return '<section class="prio-col prio-human" data-prio-desk="' + HUMAN_LIST + '"><header class="prio-head"><h3>' +
        HUMAN_LIST + '</h3><span class="prio-meta">unowned</span></header><p class="prio-note">No rows on this list.</p></section>';
    }
    var rows = hm.rows.map(function (r) {
      var c = r.card;
      var who = c ? (c.volunteer ? h(c.volunteer) : "no desk") : "";
      return '<li class="prio-row" data-prio-card="' + r.id + '"><span class="prio-ord">' + h(ordTxt(r.ord)) + "</span>" +
        '<span class="prio-card"><b>' + r.id + "</b> " + (r.type === "mail" ? "letter" : h((c && title(c)) || DASH)) + "</span>" +
        (c ? '<span class="prio-st st-' + h(c.status) + '">' + h(c.status) + "</span>" : "") +
        (who ? '<span class="prio-who">' + who + "</span>" : "") + "</li>";
    }).join("");
    var checks = hm.ties.map(function (t) {
      return '<p class="prio-tie" data-prio-check="tie">tied rank ' + ordTxt(t.ord) + ": " + t.ids.join(", ") + "</p>";
    }).join("") + hm.noDesk.map(function (x) {
      return '<p class="prio-conflict" data-prio-check="no-desk">' + ordTxt(x.ord) + ": card " + x.id + " has no desk holding it</p>";
    }).join("");
    var foot = [];
    if (hm.more) foot.push("+" + hm.more + " more");
    if (hm.unplaced) foot.push(hm.unplaced + " unplaced");
    if (hm.done) foot.push(hm.done + " done");
    return '<section class="prio-col prio-human" data-prio-desk="' + HUMAN_LIST + '"><header class="prio-head"><h3>' + HUMAN_LIST +
      '</h3><span class="prio-meta" title="Any desk that can label can edit this list. Owners come with device-link identity (card 1101).">unowned shared list</span></header>' +
      (hm.rerankedAt != null ? '<div class="prio-facts"><span class="prio-fact">re-ranked ' + ago(m.now - hm.rerankedAt) + " ago</span></div>" : "") +
      checks + '<ol class="prio-list">' + rows + "</ol>" +
      (foot.length ? '<footer class="prio-foot">' + foot.join(" \u00b7 ") + "</footer>" : "") + "</section>";
  }
  function prioHtml(m) {
    if (!m.available) {
      return '<p class="prio-unavailable" data-prio-state="unavailable">Priorities unavailable: this Wall server does not serve ' +
        "<code>GET /api/v1/labels</code> yet (card 1153 asks Loop 2 for it). Nothing is guessed; " +
        "<code>mill trail --label &lt;desk&gt;</code> reads one list.</p>";
    }
    var gaps = [];
    if (!m.served.updated) gaps.push("re-rank time");
    if (!m.served.last_activity_at) gaps.push("#0 card activity");
    if (!m.served.eta_at) gaps.push("ETA");
    if (!m.served.needs_human) gaps.push("needs-you");
    var legend = '<p class="prio-legend">Top ' + FOCUS_TOP + " workable cards per desk, as its <code>mill connect</code> focus line prints them " +
      "(not done, not parked, not held by another desk; ord ascending, ties by id). #N = ord, u = unplaced. Checks are facts, not blocks." +
      (gaps.length ? ' <span class="prio-gap" data-prio-gap="1">Not served yet, so not shown: ' + h(gaps.join(", ")) + ".</span>" : "") + "</p>";
    return legend + '<div class="prio-grid">' + humanCol(m.human, m) + m.columns.map(function (c) { return deskCol(c, m); }).join("") + "</div>";
  }

  /* ---- Live read (60 s cache) and DOM paint. */
  function getAll(url) {
    function one(cursor) {
      return global.fetch(url + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""), { cache: "no-store" }).then(function (r) {
        if (!r.ok || (r.headers.get("content-type") || "").toLowerCase().indexOf("json") < 0) return null;
        return r.json();
      }).catch(function () { return null; });
    }
    function rest(acc, cursor, pages) {
      if (!cursor || pages >= 20) return acc;
      return one(cursor).then(function (b) {
        if (!b || !Array.isArray(b.rows)) return acc;
        return rest(acc.concat(b.rows), b.next, pages + 1);
      });
    }
    return one("").then(function (b) {
      if (!b || !Array.isArray(b.rows)) return null;
      return rest(b.rows, b.next, 1);
    });
  }
  function seatedDesks() {
    var f = global._floor;
    var out = [];
    (f && Array.isArray(f.agents) ? f.agents : []).forEach(function (a) {
      var d = String((a && a.owner) || "").trim();
      if (d && out.indexOf(d) < 0) out.push(d);
    });
    return out;
  }
  var _live = { rows: undefined, at: 0, busy: false };
  function prioLoad(force) {
    if (!global.fetch || _live.busy) return;
    if (!force && _live.rows !== undefined && Date.now() - _live.at < 60000) return;
    _live.busy = true;
    _live.at = Date.now();
    getAll("/api/v1/labels?project=" + encodeURIComponent("Office") + "&limit=500").then(function (rows) {
      _live.rows = rows;
      _live.busy = false;
      paintPriorities();
      if (typeof global.wallDesksRepaint === "function") global.wallDesksRepaint();
    }, function () { _live.busy = false; _live.rows = null; paintPriorities(); });
  }
  function prioDeskTops(n) {
    /* DESKS rows: each desk's top n workable cards, 1-based pos. null until the labels read lands
     * (or when the route is missing), so DESKS leaves the line out rather than guess. */
    if (!global._prioritiesCtx) prioLoad(false);
    var ctx = global._prioritiesCtx || (_live.rows ? { rows: _live.rows, desks: seatedDesks() } : null);
    if (!ctx || !Array.isArray(ctx.rows)) return null;
    var out = {};
    prioModel(ctx).columns.forEach(function (c) {
      out[c.desk] = c.top.slice(0, n || 3).map(function (r) {
        return { pos: r.pos, id: r.id, ord: r.ord, title: r.title, overdue: r.overdue };
      });
    });
    return out;
  }
  function paintPriorities() {
    var doc = global.document;
    var box = doc && doc.getElementById("priorities-body");
    if (!box) return;
    var sample = global._prioritiesCtx;
    if (!sample && _live.rows === undefined) {
      prioLoad(false);
      if (!box.firstChild) box.innerHTML = '<p class="prio-note">Loading priorities\u2026</p>';
      return;
    }
    var ctx = sample || { rows: _live.rows, desks: seatedDesks() };
    var scroll = box.scrollTop;
    box.innerHTML = prioHtml(prioModel(ctx));
    box.scrollTop = scroll;
  }
  var _timer = 0;
  function ensurePrioritiesPaint() {
    /* Tab enter: paint now, refresh the read at most once a minute while the pane is on. */
    if (!global._prioritiesCtx) prioLoad(false);
    paintPriorities();
    if (_timer || !global.setInterval) return;
    _timer = global.setInterval(function () {
      var pane = global.document && global.document.getElementById("pane-priorities");
      if (!pane || !pane.classList.contains("on")) { global.clearInterval(_timer); _timer = 0; return; }
      prioLoad(false);
    }, 60000);
  }

  var api = {
    PRIO_FOCUS_TOP: FOCUS_TOP,
    prioRank: prioRank,
    prioActionable: prioActionable,
    prioFocusTop: prioFocusTop,
    prioCards: prioCards,
    prioModel: prioModel,
    prioHtml: prioHtml,
    prioDeskTops: prioDeskTops,
    paintPriorities: paintPriorities
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.ensurePrioritiesPaint = ensurePrioritiesPaint;
  global.WallPriorities = api;
  global.WALL_UI_DEFAULT_PRIORITIES_PAINT = "WALL_UI_DEFAULT_PRIORITIES_PAINT";
})(typeof window !== "undefined" ? window : globalThis);
