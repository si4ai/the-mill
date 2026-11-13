/* WALL_UI_DEFAULT_RD_VIEW - HTML for the Wall redesign (rail, strip, chips, six tabs).
 * Marker: WALL_UI_DEFAULT_RD_VIEW
 * Pure: takes the models from rd-model.js and returns HTML strings. No reads, no DOM.
 * Rows are short sentences; no raw field names. A spot the model left null is left out. */
(function (global) {
  "use strict";
  var R = global.WallRd;

  function h(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function clock(t) {
    if (t == null) return "";
    var d = new Date(t), now = new Date();
    var hm = (d.getHours() < 10 ? "0" : "") + d.getHours() + ":" + (d.getMinutes() < 10 ? "0" : "") + d.getMinutes();
    if (d.toDateString() === now.toDateString()) return hm;
    return d.getDate() + " " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
  }
  function rank(pos, ord) {
    return '<span class="rd-rank"' + (ord != null ? ' title="ord ' + h(ord) + '"' : "") + ">#" + h(pos) + "</span>";
  }
  function item(key) {
    var it = R.itemOf(key);
    if (!it) return '<span class="rd-on-item">' + h(key) + "</span>";
    var tab = { mail: "mail", todo: "todo", hold: "collab", score: "score" }[it.kind];
    return '<a class="rd-on-item" href="#' + tab + '" data-rd-go="' + h(tab) + '" data-rd-sel="' + h(it.key) + '">' + h(it.key) + "</a>";
  }
  function chip(text, cls) { return '<span class="rd-chip' + (cls ? " " + cls : "") + '">' + h(text) + "</span>"; }
  function deskChip(name) { return '<button type="button" class="rd-chip rd-desk-chip" data-rd-desk="' + h(name) + '">' + h(name) + "</button>"; }
  function empty(text) { return '<p class="rd-empty-line">' + h(text) + "</p>"; }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }

  /* ---- scope rail ---- */
  function railHtml(rosters, base) {
    var sc = base.scope;
    var names = (rosters || []).filter(function (r) { return r.desks || sc.rosters.indexOf(r.name) >= 0; })
      .map(function (r) { return r.name; });
    sc.rosters.forEach(function (r) { if (names.indexOf(r) < 0) names.unshift(r); });
    names.sort(function (a, b) { return (a === "Office" ? -1 : b === "Office" ? 1 : a.localeCompare(b)); });
    var rosterRows = names.map(function (n) {
      var on = sc.rosters.indexOf(n) >= 0;
      return '<button type="button" class="rd-rail-row rd-check' + (on ? " on" : "") + '" data-rd-roster="' + h(n) + '" aria-pressed="' + on + '">' +
        '<span class="rd-box" aria-hidden="true"></span><span class="rd-nm">' + h(n) + "</span></button>";
    }).join("");
    var desks = base.all.slice().sort(function (a, b) {
      return (b.connected ? 1 : 0) - (a.connected ? 1 : 0) || (b.lastSeenAt || 0) - (a.lastSeenAt || 0) || a.name.localeCompare(b.name);
    });
    var deskRows = desks.length ? desks.map(function (d) {
      var dot = d.connected ? (d.state === "working" ? "" : " idle") : " disconnected";
      var agoText = d.connected ? "now" : R.ago(base.now - d.lastSeenAt);
      return '<button type="button" class="rd-rail-row rd-check' + (d.checked ? " on" : "") + (d.connected ? "" : " away") + '" data-rd-deskpick="' + h(d.name) + '" aria-pressed="' + d.checked + '">' +
        '<span class="rd-box" aria-hidden="true"></span><span class="rd-rail-dot' + dot + '"></span><span class="rd-nm">' + h(d.name) + '</span><span class="rd-ago">' + h(agoText) + "</span></button>";
    }).join("") : '<p class="rd-rail-hint">' + (base.agentsKnown ? "No desk seen in this range." : "Loading\u2026") + "</p>";
    var ranges = R.RANGES.map(function (k) {
      return '<button type="button" data-rd-range="' + k + '"' + (k === sc.range ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + (k === "today" ? "Today" : k) + "</button>";
    }).join("");
    return '<div class="rd-rail-sec"><span class="rd-rail-lbl">Rosters</span><p class="rd-rail-hint">Pick one or more.</p>' + rosterRows + "</div>" +
      '<div class="rd-rail-sec"><span class="rd-rail-lbl">Desks</span><p class="rd-rail-hint">Seen ' + h(R.rangeText(sc.range)) + ".</p>" + deskRows + "</div>" +
      '<div class="rd-rail-sec"><span class="rd-rail-lbl">Time</span><div class="rd-time-range" role="group" aria-label="Time range">' + ranges + "</div></div>";
  }

  function stripHtml(cards, tab) {
    return cards.map(function (c) {
      var on = c.tab === tab;
      var n = c.n == null ? "\u2026" : c.n;
      return '<button type="button" class="rd-kpi' + (on ? " on" : "") + (c.warn ? " warn" : "") + '" role="tab" aria-selected="' + on + '" data-rd-tab="' + c.tab + '">' +
        '<span class="rd-cue">' + h(c.label) + "</span><b>" + h(n) + '</b><span class="rd-cue">' + h(c.n == null ? "" : c.cue) + "</span></button>";
    }).join("");
  }
  function heroHtml(x) { return "<b>" + h(x.lead) + "</b>" + (x.rest ? " " + h(x.rest) : ""); }

  function chipsHtml(base) {
    var sc = base.scope;
    var off = base.all.filter(function (d) { return !d.checked; }).length;
    var deskText = off ? (base.all.length - off) + " of " + base.all.length : "all seen " + R.rangeText(sc.range);
    var html = '<button type="button" class="rd-filter-open" data-rd-filters="open">Filter</button>';
    sc.rosters.forEach(function (r) {
      html += '<span class="rd-filter-chip"><b>Roster:</b> ' + h(r) + ' <button type="button" data-rd-unroster="' + h(r) + '" aria-label="Remove ' + h(r) + ' roster">\u00d7</button></span>';
    });
    html += '<span class="rd-filter-chip"><b>Desks:</b> ' + h(deskText) + (off ? ' <button type="button" data-rd-clear="desks" aria-label="Clear desk filter">\u00d7</button>' : "") + "</span>";
    html += '<span class="rd-filter-chip"><b>Time:</b> ' + h(sc.range === "today" ? "Today" : sc.range) + (sc.range !== "7d" ? ' <button type="button" data-rd-clear="time" aria-label="Back to 7 days">\u00d7</button>' : "") + "</span>";
    return html;
  }

  /* ---- DESKS ---- */
  var SORT_LABEL = { urgency: "Urgency", az: "A-Z", za: "Z-A", recent: "Recent activity" };
  function waitHtml(w) {
    if (!w || (!w.letters && !w.cards)) return "";
    var parts = [];
    if (w.letters) parts.push(plural(w.letters, "letter") + " waiting" + (w.overDay ? " \u00b7 " + w.overDay + " older than a day" : ""));
    if (w.cards) parts.push(plural(w.cards, "card") + " waiting");
    var cls = w.overDay >= 2 ? " older" : w.overDay ? " hot" : "";
    return '<span class="rd-wait' + cls + '">' + h(parts.join(", ")) + "</span>";
  }
  function priosLine(p) {
    if (p == null) return "";
    if (!p.length) return '<span class="rd-here-prios empty">no priorities set</span>';
    var plain = p.map(function (x) { return "#" + x.pos + " todo-" + x.id + " " + x.title + " (ord " + x.ord + ")"; }).join(" \u00b7 ");
    return '<span class="rd-here-prios" title="' + h(plain) + '">' + p.map(function (x) {
      return rank(x.pos, x.ord) + " todo-" + h(x.id) + " " + h(x.title);
    }).join(" \u00b7 ") + "</span>";
  }
  function rowChips(r) {
    var s = r.scores;
    if (!s || !s.any) return r.rosterOff ? '<span class="rd-here-scores">' + rosterChip(r.rosterOff) + "</span>" : "";
    var bits = [];
    if (r.on) bits.push('<span class="rd-on-item">' + h(r.on) + "</span>");
    if (r.state === "working" && r.age) bits.push(h(r.age) + " running");
    else if (r.idle) bits.push("idle " + h(r.idle));
    if (s.lastRun) bits.push("last run " + h(s.lastRun));
    var html = '<span class="rd-here-scores"><span class="rd-score-chip doing' + (s.lastRunOff ? " off" : "") + '"><span class="rd-chip-lbl">doing</span> ' + bits.join(" \u00b7 ") + "</span>";
    if (s.system) html += '<span class="rd-score-chip system"><span class="rd-chip-lbl">system</span> <b>' + h(s.system.value) + "</b> commands</span>";
    var bad = s.health.filter(function (x) { return x.off; })[0];
    if (bad) html += '<span class="rd-score-chip off"><span class="rd-chip-lbl">' + h(bad.label.toLowerCase()) + "</span> <b>" + h(bad.value) + " / " + h(bad.target) + "</b></span>";
    if (r.rosterOff) html += rosterChip(r.rosterOff);
    return html + "</span>";
  }
  function rosterChip(x) {
    return '<span class="rd-score-chip roster off" title="an off-target score on a roster this desk sits on, not this desk\'s own"><span class="rd-chip-lbl">' + h(x.roster) + "</span> " +
      h(x.label.toLowerCase()) + " <b>" + h(x.value) + (x.target ? " / " + h(x.target) : "") + "</b></span>";
  }
  function deskRowHtml(r, selected, now) {
    var on = r.name === selected ? " on" : "";
    var doing, meta;
    if (!r.connected) {
      var last = r.leftover ? r.leftover : (r.recent && r.recent.thing ? r.recent.type + " " + r.recent.thing : "");
      doing = '<span class="rd-here-doing is-idle">' + (last ? "last: " + h(last) : "no recent activity") + "</span>";
      meta = '<span class="rd-here-meta"><span class="rd-last-seen">last seen ' + h(R.ago(now - r.lastSeenAt)) + "</span>" +
        (r.leftoverOn ? '<span class="rd-on-item">' + h(r.leftoverOn) + "</span>" : "") + "</span>";
    } else {
      if (r.state === "working") doing = '<span class="rd-here-doing">' + h(r.doing) + "</span>";
      else {
        var lastD = r.leftover || (r.last && r.last.doing) || "";
        doing = '<span class="rd-here-doing is-idle">' + h(r.state) + (lastD ? ' <span class="rd-last">\u00b7 last: ' + h(lastD) + "</span>" : "") + "</span>";
      }
      meta = '<span class="rd-here-meta">' + (r.on ? '<span class="rd-on-item">' + h(r.on) + "</span>" : "") +
        (r.age || r.idle ? '<span class="rd-age">' + h(r.age || r.idle) + "</span>" : "") + waitHtml(r.wait) + "</span>";
    }
    var state = r.connected ? r.state : "disconnected";
    return '<div class="rd-here-line' + (r.connected ? "" : " away") + '">' +
      '<button type="button" class="rd-here-row' + on + '" data-rd-pickdesk="' + h(r.name) + '">' +
      '<span class="rd-here-dot ' + h(state) + '"></span><span class="rd-here-name">' + h(r.name) + "</span>" +
      '<span class="rd-here-state ' + h(state) + '">' + h(state) + "</span>" +
      doing + meta + priosLine(r.prios) + (r.connected ? rowChips(r) : "") + "</button></div>";
  }
  function desksListHtml(m, now) {
    if (!m.known) return '<div class="rd-loading">Loading desks\u2026</div>';
    var html = '<div class="rd-here-section">Connected \u00b7 ' + m.connected.length + "</div>" +
      (m.connected.length ? m.connected.map(function (r) { return deskRowHtml(r, m.selected, now); }).join("")
        : '<div class="rd-empty-line">No desk is connected on this scope. Ask your agent to join.</div>');
    if (m.away.length) {
      html += '<div class="rd-here-section away">Disconnected \u00b7 ' + m.away.length + "</div>" +
        m.away.map(function (r) { return deskRowHtml(r, m.selected, now); }).join("");
    }
    return html;
  }
  function srow(label, last, opts) {
    opts = opts || {};
    var lt = last === "" || last == null ? '<span class="rd-lt rd-gap">not sent</span>'
      : '<span class="rd-lt">' + h(last) + (opts.target ? '<span class="rd-tgt"> / ' + h(opts.target) + "</span>" : "") + (opts.note ? '<span class="rd-tgt"> \u00b7 ' + h(opts.note) + "</span>" : "") + "</span>";
    return '<div class="rd-srow' + (opts.off ? " off" : "") + '"><span class="rd-sname"' + (opts.title ? ' title="' + h(opts.title) + '"' : "") + ">" + h(label) + "</span>" + lt +
      (opts.spark || '<span class="rd-gap"></span>') + '<span class="rd-vol">' + h(opts.vol || "") + "</span></div>";
  }
  function spark(vals, title) {
    if (!vals || !vals.length) return '<span class="rd-si-spark rd-si-empty">\u2014</span>';
    var max = Math.max.apply(null, vals) || 1;
    return '<span class="rd-si-spark" aria-hidden="true"' + (title ? ' title="' + h(title) + '"' : "") + ">" + vals.map(function (x) {
      return '<i class="s' + Math.max(0, Math.round((x / max) * 8)) + '"></i>';
    }).join("") + "</span>";
  }
  function scoresBlock(dd) {
    var r = dd.desk, s = r.scores;
    if (!s) return "";
    var D = s.doing;
    var nowLine = r.state === "working"
      ? (r.on ? "on " + item(r.on) + " \u00b7 " : "") + "running " + h(r.age) + (s.lastRun ? ' \u00b7 last run <span class="rd-how' + (s.lastRunOff ? " off" : "") + '">' + h(s.lastRun) + "</span>" : "")
      : (r.connected ? h(r.state) + (r.idle ? " " + h(r.idle) : "") : "disconnected") + (s.lastRun ? ' \u00b7 last run <span class="rd-how' + (s.lastRunOff ? " off" : "") + '">' + h(s.lastRun) + "</span>" : "");
    var leaf = function (k, fmt) { var x = D[k]; return srow(R.kpiLabel(k), x ? fmt(x.value) : "", { off: x && x.off, title: k }); };
    var ms = function (v) { return R.msText(v); };
    var word = function (v) { return String(v).replace(/^tw_/, "").replace(/_/g, " "); };
    var rows = leaf("doing.task.dwell_active_ms", ms) + leaf("doing.task.dwell_idle_ms", ms);
    if (D["doing.task.dwell_waiting_ms"]) rows += leaf("doing.task.dwell_waiting_ms", ms);
    rows += leaf("doing.task.last_run", word) + leaf("doing.task.end_reason", word);
    /* TODO(card 1194): "Doing time today" is not served yet, so it has no row. */
    if (dd.runs && dd.runs.length) {
      rows += srow("Last runs (active time)", "", { spark: spark(dd.runs.map(function (x) { return x.ms; }), "active time per finished run, oldest to newest"), vol: "from score runs, oldest to newest" }).replace('<span class="rd-lt rd-gap">not sent</span>', '<span class="rd-lt"></span>');
    }
    var sys = s.system ? srow("Commands", s.system.value, { title: "system", vol: s.system.note }) : "";
    var health = s.health.map(function (x) { return srow(x.label, x.value, { target: x.target, off: x.off, title: x.kpi, vol: x.note }); }).join("");
    var rost = dd.rosterScores.map(function (x) {
      return "<div><h5>" + h(x.roster) + ' <span class="rd-tag">roster scores</span></h5>' + x.rows.map(function (k) {
        return srow(k.label, k.value, { target: k.target, off: k.off, title: k.kpi, vol: k.note });
      }).join("") + "</div>";
    }).join("");
    var offN = s.off;
    return '<section class="rd-block scores"><h3>SCORES <span class="rd-sub">' + (offN ? '<span class="offn">' + offN + " off target</span> \u00b7 " : "on target \u00b7 ") + "platform scores for this desk</span></h3>" +
      '<div class="rd-score-stack"><div class="rd-sg lead"><h4>Doing</h4><div class="rd-doing-now">' + nowLine + "</div>" + rows + "</div>" +
      (sys || health ? '<div class="rd-sg system"><h4>System</h4>' + sys + health + "</div>" : "") +
      (rost ? '<div class="rd-sg rosters"><h4>Rosters <span class="rd-sub">the roster\u2019s scores, not this desk\u2019s</span></h4><div class="rd-roster-cols">' + rost + "</div></div>" : "") +
      "</div></section>";
  }
  function attnHtml(a) {
    var kindLbl = { letter: "letter", prio: "prio", card: "card" }[a.kind] || a.kind;
    var flag = a.kind === "prio" ? rank(a.rank, a.ord) : h(a.flag || "");
    return '<div class="rd-attn' + (a.heat ? " " + a.heat : "") + '"><span class="rd-kind ' + h(a.kind) + '">' + h(kindLbl) + "</span>" +
      '<span class="rd-flag' + (a.heat === "older" ? " days" : a.heat === "hot" ? " day" : "") + '">' + flag + "</span>" +
      '<span class="rd-title">' + item(a.id) + " " + h(a.title) + (a.note ? '<span class="rd-note">' + h(a.note) + "</span>" : "") + "</span>" +
      '<span class="rd-when">' + h(a.when || "") + "</span></div>";
  }
  function deskDetailHtml(dd, now) {
    if (!dd) return '<div class="rd-empty-line">Pick a desk.</div>';
    var r = dd.desk;
    var state = r.connected ? r.state : "disconnected";
    var text = r.state === "working" ? h(r.doing)
      : r.connected ? h(r.state) + ((r.last && r.last.doing) || r.leftover ? " \u00b7 last: " + h(r.leftover || r.last.doing) : "")
      : "last: " + h(r.leftover || (r.recent ? r.recent.type + " " + r.recent.thing : "no recent activity"));
    var facts = [];
    if (r.connected && r.on) facts.push("on " + item(r.on));
    if (r.age) facts.push("for " + h(r.age));
    if (r.idle) facts.push("idle " + h(r.idle));
    if (!r.connected && r.lastSeenAt != null) facts.push("last seen " + h(R.ago(now - r.lastSeenAt)));
    if (r.wait && r.wait.letters) facts.push(h(plural(r.wait.letters, "letter")) + " waiting");
    if (r.wait && r.wait.cards) facts.push(h(plural(r.wait.cards, "card")) + " waiting");
    if (r.rosters.length) facts.push("on " + h(r.rosters.join(", ")));
    var html = '<div class="rd-desk-head"><b>' + h(r.name) + '</b> <span class="rd-here-state ' + h(state) + '">' + h(state) + "</span></div>" +
      '<div class="rd-desk-doing">' + text + '<div class="rd-facts">' + facts.join(" \u00b7 ") + "</div></div>" + scoresBlock(dd);
    var attn = dd.attention.map(attnHtml).join("");
    var lettersAt = dd.attention.filter(function (a) { return a.kind === "letter"; }).length;
    if (dd.moreLetters) {
      var more = '<a class="rd-more-link" href="#mail" data-rd-go="mail">' + h(plural(dd.moreLetters, "more letter")) + " waiting</a>";
      var idx = attn.split('<div class="rd-attn').slice(0, lettersAt + 1).join('<div class="rd-attn').length;
      attn = attn.slice(0, idx) + more + attn.slice(idx);
    }
    html += '<div class="rd-desk-grid"><section class="rd-block needs"><h3>NEEDS ATTENTION <span class="rd-sub">oldest letters, then this desk\u2019s list, then stuck cards</span></h3>' +
      (attn || '<p class="rd-empty">No waiting letters, no ranked card, nothing stuck.</p>') + "</section>";
    html += '<section class="rd-block card"><h3>CARD <span class="rd-sub">current</span></h3>' + (dd.card
      ? '<div class="rd-card-title">' + item(dd.card.id) + (dd.card.title ? " \u00b7 " + h(dd.card.title) : "") + '</div><div class="rd-card-facts">' +
        (dd.card.status ? "<span>" + h(dd.card.status) + "</span>" : "") + (r.age ? "<span>for " + h(r.age) + "</span>" : "") +
        (dd.card.rank ? "<span>rank " + rank(dd.card.rank, dd.card.ord) + " on " + h(r.name) + "</span>" : "") + "</div>"
      : '<div class="rd-empty">' + (r.on ? "Doing is on " + item(r.on) + ", not a card." : "No current card.") + "</div>") + "</section>";
    if (dd.chat) {
      html += '<section class="rd-block chat"><h3>CHAT <span class="rd-sub">latest first</span></h3>' + (dd.chat.length ? dd.chat.slice(0, 4).map(function (m) {
        var to = m.tos.map(function (t) { return t.desk; }).join(", ");
        return '<div class="rd-letter"><b>' + h(m.from) + "</b> " + item("mail-" + m.id) + '<span class="rd-when">' + h(R.dur(now - m.at)) + "</span>" +
          '<span class="rd-body">' + (m.from === r.name ? "to " + h(to) + ": " : "") + h(R.firstLine(m.body, 160) || "(no text)") + "</span></div>";
      }).join("") + (dd.chat.length > 4 ? '<a class="rd-more-link" href="#mail" data-rd-go="mail">' + h(plural(dd.chat.length - 4, "older letter")) + "</a>" : "")
        : '<div class="rd-empty">No letters in this slice.</div>') + "</section>";
    }
    if (dd.holds) {
      html += '<section class="rd-block promise"><h3>PROMISE <span class="rd-sub">held files</span></h3>' + (dd.holds.length ? dd.holds.map(function (x) {
        return '<div class="rd-file-row"><code>' + h(x.resource) + "</code>" + (x.dead ? " \u00b7 holder gone" : "") + "</div>";
      }).join("") : '<div class="rd-empty">No file held.</div>') + "</section>";
    }
    if (dd.trail) {
      html += '<section class="rd-block trail"><h3>DOING TRAIL <span class="rd-sub">last ' + dd.trail.length + "</span></h3>" + (dd.trail.length ? dd.trail.map(function (t) {
        return '<div class="rd-tl' + (t.current ? " current" : "") + '"><span class="rd-when">' + h(clock(t.at)) + '</span><span class="rd-text">' + h(t.doing) +
          (t.on ? " " + item(t.on) : "") + ' <span class="rd-how">' + (t.current ? "current" : "ended: " + h(t.ended)) + "</span></span></div>";
      }).join("") : '<div class="rd-empty">No doing rows yet.</div>') + "</section>";
    }
    return html + "</div>";
  }
  function feedHtml(rows) {
    if (rows == null) return "";
    return "<h3>OFFICE ACTIVITY <span class=\"rd-sub\">latest first</span></h3>" + (rows.length ? rows.map(function (f) {
      return '<div class="rd-feed-row"><span class="rd-when">' + h(clock(f.at)) + '</span><div><span class="rd-who">' + h(f.who) + '</span><span class="rd-k ' + h(f.kind) + '">' + h(f.kind) + '</span><span class="rd-text">' + h(f.text) + "</span></div></div>";
    }).join("") : '<p class="rd-empty">Nothing in the latest activity.</p>');
  }
  function sortHtml(sort) {
    return '<span class="rd-sort-switch" role="group" aria-label="Sort desks"><span class="rd-lbl">SORT</span>' + R.SORTS.map(function (k) {
      return '<button type="button" data-rd-sort="' + k + '"' + (k === sort ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + SORT_LABEL[k] + "</button>";
    }).join("") + "</span>";
  }

  /* ---- grouped tabs ---- */
  function groupCol(label, sub, rows, cls) {
    return '<section class="rd-group-col' + (cls ? " " + cls : "") + '"><h3>' + h(label) + ' <span class="rd-sub">' + h(sub) + "</span></h3>" + rows + "</section>";
  }
  function itemRow(key, selected, head, meta, cls) {
    return '<article class="rd-item-row' + (key === selected ? " on" : "") + (cls ? " " + cls : "") + '" data-rd-pick="' + h(key) + '" tabindex="0"><div>' + head + '</div><div class="rd-item-meta">' + meta + "</div></article>";
  }
  function when(text, heat) { return text ? '<span class="rd-when' + (heat ? " " + heat : "") + '">' + h(text) + "</span>" : ""; }
  function flag(text, heat) { return text ? '<span class="rd-flag' + (heat ? " " + heat : "") + '">' + h(text) + "</span>" : ""; }

  function todoHtml(m) {
    var cols = m.groups.map(function (g) {
      var rows = g.rows.length ? g.rows.map(function (r) {
        var meta = (r.desk ? deskChip(r.desk) : chip("no desk")) +
          r.ranks.slice(0, 2).map(function (x) { return rank(x.pos, x.ord) + (x.desk !== r.desk ? '<span class="rd-dim">on ' + h(x.desk) + "</span>" : ""); }).join("") +
          flag(r.flag, r.heat) + (r.note ? "<span>" + h(r.note) + "</span>" : "") + when(r.when);
        return itemRow("todo-" + r.id, m.selected, '<span class="rd-item-id">todo-' + h(r.id) + '</span><span class="rd-item-title">' + h(r.title) + "</span>", meta);
      }).join("") : empty(g.key === "attention" ? "Nothing needs attention." : "None.");
      return groupCol(g.label, String(g.rows.length), rows);
    }).join("");
    var d = m.detail, det = "";
    if (d) {
      det = "<h3>CARD <span class=\"rd-sub\">selected</span></h3>" +
        '<div class="rd-detail-title">todo-' + h(d.id) + " \u00b7 " + h(d.title) + "</div>" +
        '<div class="rd-detail-facts">' + (d.desk ? deskChip(d.desk) : "") + "<span>" + h(d.status) + "</span>" +
        d.ranks.map(function (x) { return "<span>ranked " + rank(x.pos, x.ord) + " on " + h(x.desk) + "</span>"; }).join("") +
        (d.current ? "<span>the current doing</span>" : "") + (d.creator ? "<span>filed by " + h(d.creator) + "</span>" : "") + "</div>" +
        '<p class="rd-detail-body">' + h(d.detail) + (d.trunc ? "\u2026" : "") + "</p>" +
        (d.mentions ? "<h3>MENTIONED IN <span class=\"rd-sub\">latest letters</span></h3>" + (d.mentions.length ? d.mentions.map(feedLetter).join("") : '<p class="rd-empty">No loaded letter names this card.</p>') : "");
    }
    return split(cols, det, m.groups.length);
  }
  function feedLetter(m) {
    return '<div class="rd-feed-row"><span class="rd-when">' + h(clock(m.at)) + '</span><div><span class="rd-who">' + h(m.from) + '</span><span class="rd-k mail">mail</span><span class="rd-text">' + h(R.firstLine(m.body || m.text, 120)) + "</span></div></div>";
  }
  function split(cols, detail, n, cls) {
    return '<div class="rd-tab-split"><div class="rd-tab-groups' + (cls ? " " + cls : "") + '" style="--groups:' + Math.max(1, Math.min(n, 6)) + '">' + cols + "</div>" +
      '<aside class="rd-tab-detail">' + detail + "</aside></div>";
  }
  function mailHtml(m) {
    if (!m.groups.length) return split(groupCol("Waiting", "0", empty("No letter is waiting on a desk in this range.")), "", 1);
    var cols = m.groups.map(function (g) {
      var rows = g.rows.map(function (r) {
        return itemRow(r.key, m.selected, '<span class="rd-item-id">' + h(r.key) + '</span><span class="rd-item-title">' + h(r.text) + "</span>",
          '<span class="rd-mail-chip from">from ' + h(r.from) + '</span><span class="rd-mail-chip to">to ' + h(g.desk) + "</span>" + when(r.when, r.heat));
      }).join("") + (g.more ? '<p class="rd-more-line">' + h(plural(g.more, "more letter")) + " waiting</p>" : "");
      return groupCol("Waiting on " + g.desk, g.n + " \u00b7 oldest first" + (g.away ? " \u00b7 away" : ""), rows, g.away ? "away" : "");
    }).join("");
    var d = m.detail, det = "";
    if (d) {
      det = '<h3>LETTER <span class="rd-sub">selected</span></h3><div class="rd-detail-title">' + h(d.letter.key) + "</div>" +
        '<div class="rd-detail-facts"><span class="rd-mail-chip from">from ' + h(d.letter.from) + "</span>" + (d.waitingOn ? '<span class="rd-mail-chip to">to ' + h(d.waitingOn) + "</span>" : "") +
        when(d.letter.when + (d.letter.heat === "older" ? " \u00b7 over a day" : ""), d.letter.heat) + "</div>" +
        '<p class="rd-detail-body">' + h(d.body) + (d.trunc ? "\u2026" : "") + "</p>" +
        '<h3>THREAD <span class="rd-sub">' + h(plural(d.thread.length, "letter")) + "</span></h3>" + d.thread.map(function (t) {
          return '<div class="rd-feed-row"><span class="rd-when">' + h(t.when) + '</span><div><span class="rd-who">' + h(t.from) + '</span><span class="rd-k mail">mail</span><span class="rd-text">' + h(t.text) + "</span></div></div>";
        }).join("");
    }
    return split(cols, det, Math.min(m.groups.length, 4));
  }
  function prioritiesHtml(m) {
    var cols = m.cols.map(function (c) {
      var rows = c.rows.length ? c.rows.map(function (r) {
        return itemRow(c.desk + "|" + r.id, m.selected, rank(r.pos, r.ord) + ' <span class="rd-item-id">todo-' + h(r.id) + '</span><span class="rd-item-title">' + h(r.title) + "</span>",
          (r.stuck ? flag("no activity", "older") : "") + "<span>" + h(r.note) + "</span>" + when(r.when));
      }).join("") : empty("no priorities set");
      return groupCol(c.desk, c.sub, rows, c.away ? "away" : "");
    }).join("");
    var d = m.detail, det = "";
    if (d) {
      det = '<h3>PRIORITY <span class="rd-sub">selected</span></h3><div class="rd-detail-title">' + rank(d.pos, d.ord) + " on " + h(d.desk) + " \u00b7 todo-" + h(d.id) + "</div>" +
        '<div class="rd-detail-facts">' + deskChip(d.desk) + "<span>" + h(d.title) + "</span><span>" + h(d.status) + "</span>" + (d.volunteer ? "<span>claimed by " + h(d.volunteer) + "</span>" : "") + (d.current ? "<span>current doing</span>" : "") + "</div>" +
        '<p class="rd-detail-body">' + (d.body ? h(d.body) : "Display rank is 1-based; the stored ord is " + h(d.ord) + " (hover the rank).") + "</p>" +
        (d.offRoster.length ? '<h3>OFF ROSTER <span class="rd-sub">cards on this list from another roster</span></h3>' + d.offRoster.map(function (c) {
          return '<div class="rd-feed-row"><span class="rd-when">todo-' + h(c.id) + '</span><div><span class="rd-text">sits on ' + h(c.roster) + "</span></div></div>";
        }).join("") : "");
    }
    return split(cols, det, m.cols.length, "prios");
  }
  function scoreHtml(m) {
    if (!m.groups.length) return split(groupCol("Scores", "0", empty("No platform score on this scope yet.")), "", 1);
    var cols = m.groups.map(function (g) {
      var rows = g.rows.map(function (r) {
        var who = r.desk ? deskChip(r.desk) : chip(r.roster, "roster");
        return itemRow(r.key, m.selected, who + ' <span class="rd-item-title">' + h(r.label) + "</span>",
          '<span class="rd-lt">' + h(r.value) + (r.target ? '<span class="rd-tgt"> / ' + h(r.target) + "</span>" : "") + "</span>" +
          (r.off ? flag("off target", "older") : "") + r.meta.map(function (x) { return "<span>" + h(x) + "</span>"; }).join(""), r.off ? "off" : "");
      }).join("");
      return groupCol(g.label, (g.off ? g.off + " off \u00b7 " : "") + g.hint, rows);
    }).join("");
    var d = m.detail, det = "";
    if (d) {
      det = '<h3>SCORE <span class="rd-sub">selected</span></h3><div class="rd-detail-title">' + h(d.label) + " \u00b7 " + h(d.desk || d.roster + " roster") + "</div>" +
        '<div class="rd-detail-facts">' + (d.desk ? deskChip(d.desk) : chip(d.roster, "roster")) + '<span class="rd-lt">' + h(d.value) + (d.target ? '<span class="rd-tgt"> / ' + h(d.target) + "</span>" : "") + "</span>" +
        (d.off ? flag("off target", "older") : "<span>on target</span>") + (d.updated ? "<span>updated " + h(clock(d.updated)) + "</span>" : "") + "</div>" +
        '<p class="rd-detail-body">' + h(d.group + (d.desk ? " score for " + d.desk + "." : " score for the " + d.roster + " roster, not a desk\u2019s.")) + (d.note ? " " + h(d.note) : "") +
        (d.meta.length ? " " + h(d.meta.join(", ")) + "." : "") + "</p>" +
        (d.runs && d.runs.length ? '<h3>LAST RUNS <span class="rd-sub">oldest to newest</span></h3><div class="rd-runs">' + spark(d.runs.map(function (x) { return x.ms; })) + "</div>" +
          d.runs.slice(-5).reverse().map(function (x) {
            return '<div class="rd-feed-row"><span class="rd-when">' + h(R.msText(x.ms)) + '</span><div><span class="rd-text' + (x.phase === "failed" ? " off" : "") + '">' + h(x.phase) + (x.ended && x.ended !== x.phase ? ", " + h(x.ended) : "") + "</span></div></div>";
          }).join("") : "");
    }
    return split(cols, det, m.groups.length);
  }
  function collabHtml(m) {
    var cols = m.groups.map(function (g) {
      var rows = g.rows.length ? g.rows.map(function (r) {
        if (g.key === "rooms") {
          return itemRow(r.key, m.selected, '<span class="rd-item-title">' + h(r.name) + "</span>",
            r.who.slice(0, 4).map(deskChip).join("") + (r.who.length > 4 ? "<span>+" + (r.who.length - 4) + "</span>" : "") + "<span>" + h(plural(r.n, "letter")) + "</span>" + when(r.when));
        }
        if (g.key === "trees") {
          return itemRow(r.key, m.selected, '<span class="rd-item-title">' + h(r.name) + "</span>", (r.who ? deskChip(r.who) : "") + "<span>" + h(plural(r.n, "card")) + "</span>" + (r.title ? "<span>" + h(r.title) + "</span>" : ""));
        }
        return itemRow(r.key, m.selected, '<span class="rd-item-title">' + (r.kind === "hold" ? "<code>" + h(r.title) + "</code>" : h(r.title)) + "</span>",
          deskChip(r.desk) + chip(r.kind === "hold" ? "promise" : "waiting", "kind") + (r.note ? flag(r.note, g.key === "blocking" ? "hot" : "") : ""));
      }).join("") : empty(g.key === "blocking" ? "Nothing is blocking anyone." : g.key === "rooms" ? "No room has letters in this range." : g.key === "trees" ? "No card trees on this scope." : "No promise is held.");
      return groupCol(g.label, String(g.rows.length), rows);
    }).join("");
    var d = m.detail, det = "";
    if (d) {
      det = "<h3>" + h(d.group.toUpperCase()) + ' <span class="rd-sub">selected</span></h3><div class="rd-detail-title">' + (d.kind === "hold" ? "<code>" + h(d.title) + "</code>" : h(d.title || d.name)) + "</div>" +
        '<div class="rd-detail-facts">' + (d.desk ? deskChip(d.desk) : "") + (d.who ? d.who.slice(0, 6).map(deskChip).join("") : "") + (d.note ? "<span>" + h(d.note) + "</span>" : "") + (d.n ? "<span>" + h(plural(d.n, d.key.indexOf("tree-") === 0 ? "card" : "letter")) + "</span>" : "") + "</div>" +
        (d.letters ? '<h3>ROOM ACTIVITY <span class="rd-sub">' + h(d.name) + "</span></h3>" + d.letters.map(function (t) {
          return '<div class="rd-feed-row"><span class="rd-when">' + h(clock(t.at)) + '</span><div><span class="rd-who">' + h(t.from) + '</span><span class="rd-k mail">mail</span><span class="rd-text">' + h(t.text) + "</span></div></div>";
        }).join("") : "");
    }
    return split(cols, det, m.groups.length);
  }

  var SCOPE_TEXT = {
    desks: "", todo: "grouped by state across the roster", mail: "grouped by who they wait on, oldest first",
    priorities: "one column per desk \u00b7 ranks are 1-based, ord on hover", score: "grouped by impact \u00b7 desks are rows \u00b7 platform scores only",
    collab: "grouped by kind: what blocks someone, promises, rooms, trees"
  };
  function paneHead(tab, base, extra) {
    var sc = base.scope;
    var label = { desks: "DESKS", todo: "TODO", mail: "MAIL", priorities: "PRIORITIES", score: "SCORE", collab: "COLLAB" }[tab];
    var scope = tab === "desks" ? "" : sc.rosters.join(" + ") + " \u00b7 " + R.rangeText(sc.range) + " \u00b7 " + SCOPE_TEXT[tab];
    return '<div class="rd-pane-head">' + (tab === "desks" ? '<button type="button" class="rd-desk-back" data-rd-back="1">Back</button>' : "") +
      "<h2>" + label + "</h2>" + (extra || "") + (scope ? '<span class="rd-pane-scope">' + h(scope) + "</span>" : "") + "</div>";
  }

  global.WallRdView = {
    h: h, rail: railHtml, strip: stripHtml, hero: heroHtml, chips: chipsHtml,
    desksList: desksListHtml, deskDetail: deskDetailHtml, feed: feedHtml, sort: sortHtml, paneHead: paneHead,
    todo: todoHtml, mail: mailHtml, priorities: prioritiesHtml, score: scoreHtml, collab: collabHtml
  };
  global.WALL_UI_DEFAULT_RD_VIEW = "WALL_UI_DEFAULT_RD_VIEW";
})(typeof window !== "undefined" ? window : globalThis);
