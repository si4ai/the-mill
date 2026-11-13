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
  function localWhen(t) {
    if (t == null) return "";
    var d = new Date(t), mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getDate() + " " + mon + " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
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
  function stripHtml(cards, tab) {
    return cards.map(function (c) {
      var on = c.tab === tab;
      var n = c.n == null ? "\u2026" : c.n;
      return '<button type="button" class="rd-kpi' + (on ? " on" : "") + (c.warn ? " warn" : "") + '" role="tab" aria-selected="' + on + '" data-rd-tab="' + c.tab + '">' +
        '<span class="rd-cue">' + h(c.label) + "</span><b>" + h(n) + '</b><span class="rd-cue">' + h(c.n == null ? "" : c.cue) + "</span></button>";
    }).join("");
  }
  function heroHtml(x) { return "<b>" + h(x.lead) + "</b>" + (x.rest ? " " + h(x.rest) : ""); }


  /* ---- DESKS ---- */
  function waitHtml(w) {
    if (!w || (!w.letters && !w.cards)) return "";
    var parts = [];
    if (w.letters) parts.push(plural(w.letters, "letter") + " waiting");
    if (w.cards) parts.push(plural(w.cards, "card") + " waiting");
    return '<span class="rd-wait">' + h(parts.join(", ")) + "</span>";
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
  /* One list, most active first: working, waiting, idle, then disconnected (dimmed, last seen). */
  function desksListHtml(m, now) {
    if (!m.known) return '<div class="rd-loading">Loading desks\u2026</div>';
    var rows = m.connected.concat(m.away);
    if (!rows.length) return '<div class="rd-empty-line">No desk on this scope in this range.</div>';
    return '<div class="rd-here-section">' + h(plural(rows.length, "desk")) + " \u00b7 " + m.connected.length + " connected</div>" +
      rows.map(function (r) { return deskRowHtml(r, m.selected, now); }).join("");
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
    /* A doing score the desk never sent has no row. */
    var leaf = function (k, fmt) { var x = D[k]; return x && String(x.value) !== "" ? srow(R.kpiLabel(k), fmt(x.value), { off: x.off, title: k }) : ""; };
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
    html += '<div class="rd-desk-grid">';
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
  /* A tab's platform scores (rd-model SCORE_TABS), off target first. None served: no strip. */
  function tabScoresHtml(t) {
    if (!t || (!t.rows.length && !t.onDesk)) return "";
    var shown = t.rows.slice(0, 10);
    return '<div class="rd-tab-scores" aria-label="Scores for this tab">' + shown.map(function (k) {
      var val = h(k.value) + (k.target !== "" ? '<span class="rd-tgt"> / ' + h(k.target) + "</span>" : "");
      return '<span class="rd-score-chip' + (k.off ? " off" : "") + '" title="' + h(k.kpi + (k.note ? " \u00b7 " + k.note : "")) + '">' +
        (k.desk ? '<span class="rd-chip-lbl">' + h(k.desk) + "</span> " : "") + h(k.label) + " <b>" + val + "</b></span>";
    }).join("") + (t.rows.length > shown.length ? '<span class="rd-more-line">' + h(plural(t.rows.length - shown.length, "more score")) + "</span>" : "") +
      (t.onDesk ? '<span class="rd-score-chip ok">' + h(plural(t.onDesk, "desk score")) + " on target</span>" : "") + "</div>";
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
    return '<div class="rd-tab-split"><div class="rd-tab-groups' + (cls ? " " + cls : "") + '" data-groups="' + Math.max(1, Math.min(n, 6)) + '">' + cols + "</div>" +
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
      var top = c.rows.slice(0, 8);
      var rows = top.length ? top.map(function (r) {
        return itemRow(c.desk + "|" + r.id, m.selected, rank(r.pos, r.ord) + ' <span class="rd-item-id">todo-' + h(r.id) + '</span><span class="rd-item-title">' + h(r.title) + "</span>",
          (r.stuck ? flag("no activity", "older") : "") + "<span>" + h(r.note) + "</span>" + when(r.when));
      }).join("") + (c.rows.length > top.length ? '<p class="rd-more-line">' + h(plural(c.rows.length - top.length, "more card")) + " on this list</p>" : "") : empty("no priorities set");
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


  /* ---- COLLAB replay ---- */
  var KIND_WORD = { mail: "mail", todo: "card", hold: "promise", wake: "wake", doing: "doing", score: "score" };
  /* One icon per activity kind: 12px inline SVG, stroked in the kind's colour. */
  var KIND_SVG = {
    mail: '<path d="M1.5 3h9v6h-9z M1.5 3l4.5 3.5 4.5-3.5"/>',
    todo: '<path d="M2.5 1.5h7v9h-7z M4 4.5h4 M4 6.5h4 M4 8.5h2"/>',
    hold: '<path d="M3 5.5h6v5h-6z M4.3 5.5v-1.6a1.7 1.7 0 0 1 3.4 0v1.6"/>',
    wake: '<path d="M6 1.5v1.2 M2.2 3.2l.9.9 M9.8 3.2l-.9.9 M3.5 9.5h5 M4 9.5v-2.5a2 2 0 0 1 4 0v2.5"/>',
    doing: '<path d="M6 1.8a4.2 4.2 0 1 1-4.2 4.2"/><path d="M1.8 3.2v2.8h2.8"/>',
    score: '<circle cx="6" cy="6" r="3.2"/>'
  };
  function kindIcon(kind) {
    return '<i class="rd-ki k-' + h(kind) + '" title="' + h(KIND_WORD[kind] || kind) + '"><svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">' + (KIND_SVG[kind] || KIND_SVG.score) + "</svg></i>";
  }
  function legendHtml() {
    return '<span class="rd-rp-legend" aria-label="Kinds">' + R.REPLAY_KINDS.map(function (k) {
      return '<span class="k-' + k + '">' + kindIcon(k) + h(KIND_WORD[k]) + "</span>";
    }).join("") + "</span>";
  }
  function cloud(names) {
    return '<span class="rd-cloud" title="' + h("outside this scope: " + names.join(", ")) + '"><i aria-hidden="true">\u2601</i>outside</span>';
  }
  function partHtml(p) {
    var role = p.role ? ' data-party="' + p.role + '"' : "";
    if (p.t === "score") return '<i class="rd-sdot' + (p.off ? " off" : " on") + '" title="' + (p.off ? "off target" : "on target") + '"></i>';
    if (p.t === "desk") return '<button type="button"' + role + ' class="rd-pill st-' + h(p.state || "idle") + '" data-rd-desk="' + h(p.name) + '" title="' + h(p.name + ", " + (p.state || "idle")) + '">' + h(p.name) + "</button>";
    if (p.t === "human") return '<span' + role + ' class="rd-pill rd-human" title="the person at this office"><i aria-hidden="true">\u263a</i>' + h(p.name) + "</span>";
    if (p.t === "cloud") return cloud(p.names || [p.name]).replace("<span ", "<span" + role + " ");
    if (p.t === "item") { var it = R.itemOf(p.key); return it ? '<a class="rd-on-item" href="#' + ({ mail: "mail", todo: "todo", hold: "collab", score: "score" }[it.kind]) + '" data-rd-go="' + ({ mail: "mail", todo: "todo", hold: "collab", score: "score" }[it.kind]) + '" data-rd-sel="' + h(it.key) + '">' + h(p.v) + "</a>" : "<span>" + h(p.v) + "</span>"; }
    if (p.t === "move") return '<span class="rd-move">' + (p.from ? '<span class="rd-st">' + h(p.from) + '</span><span class="rd-arrow" aria-label="to">\u2192</span>' : '<span class="rd-arrow" aria-label="now">\u2192</span>') + '<span class="rd-st to st-' + h(p.to.toLowerCase()) + '">' + h(p.to) + "</span></span>";
    if (p.t === "quote") return '<span class="rd-q">' + h(p.v) + "</span>";
    if (p.t === "flag") return flag(p.v, "older");
    return "<span>" + h(p.v) + "</span>";
  }
  /* Tags: an activity's mill labels and its tree attachments, as small chips (full text on hover). */
  function tagWord(t) {
    return t.kind === "room" ? (t.root || "thread " + t.name) : (t.root || t.name);
  }
  function tagTitle(t) {
    return (t.kind === "room" ? "mail thread " : "card tree ") + t.name + (t.depth != null ? (t.depth === 0 ? ", the root" : ", " + t.depth + " deep") : "") + (t.root ? ": " + t.root : "");
  }
  function tagsHtml(tags, max) {
    if (!tags) return "";
    var L = tags.labels.map(function (l) { return '<span class="rd-tag rd-tag-l" title="' + h("label " + l.name + (l.ord != null ? ", position " + (l.ord + 1) : "")) + '">' + h(l.name) + "</span>"; });
    var T = tags.trees.map(function (t) { return '<span class="rd-tag rd-tag-t" title="' + h(tagTitle(t)) + '"><i aria-hidden="true">\u2442</i>' + h(tagWord(t)) + "</span>"; });
    var W = (tags.watchers || []).map(function (w) { return '<span class="rd-tag rd-tag-w" title="' + h("watched by " + w) + '"><i aria-hidden="true">\u25c9</i>' + h(w) + "</span>"; });
    var Rr = tags.roster ? ['<span class="rd-tag rd-tag-r" title="' + h("roster " + tags.roster) + '">' + h(tags.roster) + "</span>"] : [];
    var all = L.concat(T, W, Rr), n = max || all.length, more = all.length - n;
    return '<span class="rd-tags">' + all.slice(0, n).join("") + (more > 0 ? '<span class="rd-tag rd-tag-more" title="' + h(tagsText(tags)) + '">+' + more + "</span>" : "") + "</span>";
  }
  function tagsText(tags) {
    if (!tags) return "";
    return tags.labels.map(function (l) { return "label " + l.name; }).concat(tags.trees.map(tagTitle),
      (tags.watchers || []).map(function (w) { return "watched by " + w; }), tags.roster ? ["roster " + tags.roster] : []).join("; ");
  }
  function replayRow(r, fresh) {
    var read = r.read && r.read.length ? '<span class="rd-dim" title="' + h("opened by " + r.read.join(", ")) + '">opened</span>' : "";
    return '<li class="rd-rp-row k-' + h(r.kind) + (r.outside ? " cross" : "") + (fresh ? " rd-fx-in" : "") + '" data-rp="' + h(r.key) + '" data-k="' + h(r.kind) + '" data-act="' + h(r.act) + '" data-dir="' + h(r.dir || "out") + '">' +
      '<time>' + h(clock(r.at)) + "</time>" + kindIcon(r.kind) +
      '<span class="rd-rp-s">' + r.parts.map(partHtml).join(" ") + read + tagsHtml(r.tags, 6) + "</span></li>";
  }
  function replayRows(rows, fresh) {
    return rows.map(function (r) { return replayRow(r, fresh && fresh[r.key]); }).join("");
  }
  /* "300 rows (5h 10m) in 2 min": the window, the time it spans, and its playback length. */
  function speedText(rep, speed) {
    var s = Math.round(R.REPLAY_PLAY_MS / 1000 / (speed || 1)), m = Math.round(rep.ms / 60000);
    var span = m >= 2880 ? Math.round(m / 1440) + "d" : m >= 120 ? Math.floor(m / 60) + "h " + (m % 60) + "m" : m + "m";
    return plural(rep.rows.length, "row") + " (" + span + ") in " + (s >= 60 && s % 60 === 0 ? (s / 60) + " min" : s + "s");
  }
  /* Under the stage and folded, so the replay gets the height; the count says when to open it. */
  function blockingHtml(rows, open) {
    if (rows == null) return "";
    return '<details class="rd-block rd-rp-blocking" data-rp-blocking="1"' + (open ? " open" : "") + '><summary><h3>BLOCKING SOMEONE NOW <span class="rd-sub">' + h(plural(rows.length, "row")) + ' \u00b7 oldest first</span></h3></summary>' + (rows.length ? "<ul>" + rows.map(function (r) {
      var head = r.kind === "wait" ? partHtml(r.me) + " <span>is waiting on</span> " + (r.on ? partHtml(r.on) : "")
        : r.kind === "unread" ? "<span>" + h(r.title.replace(/ waiting on .*$/, "")) + " waiting on</span> " + partHtml(r.me)
        : "<span>promise</span> <code>" + h(r.title) + "</code> <span>held by</span> " + partHtml(r.me);
      return "<li>" + head + (r.note ? " " + flag(r.note, r.kind === "unread" ? "older" : "hot") : "") + "</li>";
    }).join("") + "</ul>" : empty("Nothing is blocking anyone.")) + "</details>";
  }
  /* ---- The overview: the whole loaded history as a bar graph of row counts ----
   * One bar per time bucket, height by count (linear). Bars are stacked by kind when a
   * bucket has more than one. The dim copy is the whole record; the lit copy is clipped
   * to the playhead, so the played part is bright. The box is the slice the big pane
   * shows at the playhead ([t - span, t]); drag it (grab hand) to slide the window, or
   * click outside it to jump. */
  var TRACE_W = 1000, TRACE_H = 40;
  function overviewHtml(rep) {
    var ov = R.replayOverview(rep, 160), w = TRACE_W / ov.n, bars = "", lit = "", kinds = R.REPLAY_KINDS;
    for (var i = 0; i < ov.n; i++) {
      if (!ov.total[i] || !ov.peak) continue;
      var x = (i * w).toFixed(1), bw = Math.max(1, w - 0.4).toFixed(1), y = TRACE_H, stack = [];
      kinds.forEach(function (k) {
        var c = ov.kinds[k] ? ov.kinds[k][i] : 0;
        if (!c) return;
        var h = TRACE_H * c / ov.peak;
        y -= h;
        stack.push({ k: k, y: y, h: h });
      });
      stack.forEach(function (b) {
        var r = '<rect class="k-' + b.k + '" x="' + x + '" y="' + b.y.toFixed(1) + '" width="' + bw + '" height="' + Math.max(0.5, b.h).toFixed(1) + '"/>';
        bars += r; lit += r;
      });
    }
    var vp = R.replayViewport(rep, rep.until, ov), X = function (f) { return (f * TRACE_W).toFixed(1); };
    var end0 = rep.live ? null : rep.until;
    function ovBtn(dir, label) {
      var can = R.replayPanCan ? R.replayPanCan(rep, end0, dir) : dir < 0;
      return '<button type="button" class="rd-rp-ov-btn" data-rp-ov-dir="' + dir + '"' +
        (can ? "" : " disabled") + ' aria-label="' + label + '" title="' + label + '">' +
        (dir < 0 ? "\u2039" : "\u203a") + "</button>";
    }
    return '<div class="rd-rp-ov-row">' +
      ovBtn(-1, "Previous 100") +
      '<div class="rd-rp-trace rd-rp-ov" data-rp-ov="1" data-lo="' + ov.lo + '" data-hi="' + ov.hi + '" role="slider" tabindex="0" aria-label="Replay position; drag the box or use the previous 100 and next 100 arrows" aria-valuemin="0" aria-valuemax="1000" aria-valuenow="1000" title="' + h(plural(rep.total, "row") + " loaded \u00b7 drag the box to move the window, or use the arrows for the previous or next 100") + '">' +
      '<svg viewBox="0 0 ' + TRACE_W + " " + TRACE_H + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<g class="rd-rp-bars rd-rp-bars-dim">' + bars + "</g>" +
      '<clipPath id="rd-rp-played"><rect data-rp-clip="1" x="0" y="0" width="' + X(vp.at) + '" height="' + TRACE_H + '"/></clipPath>' +
      '<g class="rd-rp-bars rd-rp-bars-lit" clip-path="url(#rd-rp-played)">' + lit + "</g>" +
      '<rect class="rd-rp-vp" data-rp-vp="1" x="' + X(vp.lo) + '" y="1" width="' + Math.max(2, (vp.hi - vp.lo) * TRACE_W).toFixed(1) + '" height="' + (TRACE_H - 2) + '"/>' +
      '<line class="rd-rp-tr-head" data-rp-head="1" x1="' + X(vp.at) + '" y1="0" x2="' + X(vp.at) + '" y2="' + TRACE_H + '"/>' +
      "</svg></div>" +
      ovBtn(1, "Next 100") +
      "</div>";
  }
  /* ---- The two subtabs: the same stage, flipped ----
   * Desks: fixed pills are the desks (office, then the pick, then one outside cloud). Activity:
   * fixed pills are the six kinds. Each pill heads a lane; items travel out along it as they
   * age. One axis config turns both left to right or top to bottom. */

  /* One shared details card: kind (with its colour swatch), title, local time and relative
   * age, the desks attached to the activity, and any labels, trees, watchers or roster. */
  var TIP_ROLE = {
    mail: { from: "sender", holders: "receiver", waiting: "" },
    todo: { from: "from", holders: "to", waiting: "" },
    hold: { from: "from", holders: "holder", waiting: "waiting" },
    wake: { from: "waker", holders: "woken", waiting: "" },
    doing: { from: "", holders: "doing", waiting: "" },
    score: { from: "", holders: "score", waiting: "" }
  };
  function tipTitle(row) {
    if (row && row.text) return row.text;
    var q = ((row && row.parts) || []).filter(function (p) { return p.t === "quote" || p.t === "item"; })[0];
    return q ? (q.v || "") : "";
  }
  function tipDesks(row) {
    var st = (row && row.state) || {}, kind = (row && row.kind) || "", roles = TIP_ROLE[kind] || TIP_ROLE.doing;
    var bits = [], arrow = false;
    function add(role, names) {
      (names || []).forEach(function (n) {
        if (!n || !role) return;
        bits.push('<span class="rd-rp-tip-desk">' + h(role) + " " + h(n) + "</span>");
      });
    }
    if (roles.from && (st.from || []).length && roles.holders && (st.holders || []).length) {
      add(roles.from, st.from);
      bits.push('<span class="rd-rp-tip-arrow" aria-hidden="true">\u2192</span>');
      add(roles.holders, st.holders);
      arrow = true;
    } else {
      add(roles.holders, st.holders);
      add(roles.from, st.from);
    }
    add(roles.waiting, st.waiting);
    return bits.length ? '<div class="rd-rp-tip-desks">' + bits.join(arrow ? "" : " ") + "</div>" : "";
  }
  var SPAN_END_WORD = { finished: "finished", failed: "failed", stale: "went stale", cleared: "cleared", drop: "released",
    force: "forced", expire: "expired", handoff: "handed on", replaced: "taken again", ended: "ended" };
  function replayTip(row, now, span) {
    if (!row) return "";
    var word = KIND_WORD[row.kind] || row.kind || "";
    var title = tipTitle(row);
    var when = localWhen(row.at), rel = row.at != null && now != null ? R.ago(now - row.at) : "";
    var time = when || rel ? '<div class="rd-rp-tip-time">' + (when ? "<time>" + h(when) + "</time>" : "") + (when && rel ? " \u00b7 " : "") + (rel ? h(rel) : "") + "</div>" : "";
    var tags = tagsHtml(row.tags, 8);
    var spanHtml = "";
    if (span && span.start != null) {
      var started = localWhen(span.start);
      var ended = span.open ? "ongoing" : (span.end != null ? localWhen(span.end) : "");
      var dms = span.open && now != null ? now - span.start : (span.end != null ? span.end - span.start : null);
      var length = dms != null ? (R.msText ? R.msText(dms) : "") : "";
      var how = span.ended && span.how ? (SPAN_END_WORD[span.how] || span.how) : "";
      spanHtml = '<div class="rd-rp-tip-span">' +
        (started ? "<time>" + h(started) + "</time>" : "") +
        (started && ended ? " \u00b7 " : "") +
        (span.open ? h("ongoing") : (ended ? "<time>" + h(ended) + "</time>" : "")) +
        (length ? " \u00b7 " + h(length) : "") + (how ? " \u00b7 " + h(how) : "") +
        "</div>";
      if (span.item || row.item) spanHtml += '<div class="rd-rp-tip-on">' + h(span.item || row.item) + "</div>";
    }
    return '<div class="rd-rp-tip-k k-' + h(row.kind) + '"><i class="rd-rp-swatch" aria-hidden="true"></i>' + h(word) + "</div>" +
      (title ? '<div class="rd-rp-tip-title">' + h(title) + "</div>" : "") + time + spanHtml + tipDesks(row) +
      (tags ? '<div class="rd-rp-tip-tags">' + tags + "</div>" : "");
  }
  function replayLaneTip(opts) {
    opts = opts || {};
    var n = opts.count || 0, sum = n === 1 ? "1 in the window" : n + " in the window";
    var head = opts.kind
      ? '<div class="rd-rp-tip-k k-' + h(opts.kind) + '"><i class="rd-rp-swatch" aria-hidden="true"></i>' + h(KIND_WORD[opts.kind] || opts.kind) + "</div>"
      : '<div class="rd-rp-tip-title">' + h(opts.name || "") + "</div>";
    return head + '<div class="rd-rp-tip-sum">' + h(sum) + "</div>";
  }
  function replayOverflowTip(rows, now) {
    rows = rows || [];
    var n = rows.length, max = 12, extra = n > max ? n - max : 0;
    var kind = n && rows.every(function (r) { return r.kind === rows[0].kind; }) ? rows[0].kind : "";
    var word = kind ? (KIND_WORD[kind] || kind) : "more";
    var head = kind
      ? '<div class="rd-rp-tip-k k-' + h(kind) + '"><i class="rd-rp-swatch" aria-hidden="true"></i>' + h("+" + n + " " + word) + "</div>"
      : '<div class="rd-rp-tip-title">+' + h(String(n)) + " more</div>";
    var hits = rows.slice(0, max).map(function (row) {
      var w = KIND_WORD[row.kind] || row.kind || "";
      var title = tipTitle(row);
      var desks = ((row.state && row.state.holders) || []).concat((row.state && row.state.from) || []);
      var who = desks.filter(function (d, i) { return d && desks.indexOf(d) === i; }).join(", ");
      return '<div class="rd-rp-tip-hit k-' + h(row.kind) + '"><i class="rd-rp-swatch" aria-hidden="true"></i><span>' +
        h(w) + (title ? " \u00b7 " + h(title) : "") + (who ? " \u00b7 " + h(who) : "") + "</span></div>";
    }).join("");
    return head + '<div class="rd-rp-tip-list">' + hits + (extra ? '<div class="rd-rp-tip-sum">+' + extra + " more</div>" : "") + "</div>";
  }
  function withLaneTip(html, tab) {
    return html.replace(/<(span|button)\b/, "<$1" + (tab ? ' tabindex="0"' : "") + ' data-rp-tip="lane"');
  }

  function laneHead(l) {
    var pill = l.t === "kind" ? withLaneTip('<span class="rd-pill rd-kind k-' + h(l.id) + '" aria-label="' + h(KIND_WORD[l.id] || l.name) + '">' + kindIcon(l.id) + h(KIND_WORD[l.id] || l.name) + "</span>", true)
      : l.t === "desk" ? withLaneTip(partHtml({ t: "desk", name: l.name, state: l.state }), false)
      : l.t === "human" ? withLaneTip(partHtml({ t: "human", name: l.name }), true)
      : l.t === "cloud" ? withLaneTip(partHtml({ t: "cloud", names: l.names && l.names.length ? l.names : ["desks off this pick"] }), true)
      : withLaneTip('<span class="rd-pill rd-office" aria-label="office, rows no desk sent">office</span>', true);
    var locks = l.t === "desk" ? '<span class="rd-rp-locks" data-rp-locks="' + h(l.id) + '"></span>' : "";
    return '<div class="rd-rp-lane" data-lane="' + h(l.id) + '">' + pill + locks + "</div>";
  }
  function stageHtml(rep, view) {
    var lanes = view === "activity" ? R.replayKindLanes() : rep.lanes;
    if (!lanes.length) return '<div class="rd-rp-stage rd-rp-empty">No desks on this pick.</div>';
    var cols = lanes.map(function (l) { return '<div class="rd-rp-col" data-col="' + h(l.id) + '"></div>'; }).join("");
    return '<div class="rd-rp-stage' + (lanes.length > 10 ? " rd-rp-many" : "") + '" data-rp-lanes="' + lanes.length + '" data-rp-view="' + view + '">' +
      '<div class="rd-rp-heads">' + lanes.map(laneHead).join("") + "</div>" +
      '<div class="rd-rp-rain" data-rp-rain="1">' + cols + '<div class="rd-rp-field" data-rp-field="' + view + '"></div></div></div>';
  }
  /* The replay shell: only the two subtabs' shared controls, the overview, and the stage.
   * The playhead, the viewport and the items are drawn by rd-app as it plays. */
  function replayHtml(rep, ui) {
    ui = ui || {};
    if (ui && ui.speed == null && arguments[2] && arguments[2].speed != null) ui = arguments[2];
    var counts = R.REPLAY_COUNTS.map(function (n) {
      var on = n === rep.count;
      return '<button type="button" data-rp-count="' + n + '"' + (on ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ' title="' + h(n + " rows in the window") + '">' + n + "</button>";
    }).join("");
    var speeds = R.REPLAY_SPEEDS.map(function (x) {
      return '<button type="button" data-rp-speed="' + x + '"' + (x === ui.speed ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + (x === 0.25 ? "\u00bc" : x === 0.5 ? "\u00bd" : x) + "x</button>";
    }).join("");
    var view = ui.view === "activity" ? "activity" : "desks";
    var dir = (ui.dirs && ui.dirs[view]) === "tb" ? "tb" : R.REPLAY_DIR_DEFAULT[view];
    var dirBtn = '<button type="button" class="rd-rp-btn rd-rp-dir" data-rp-dir="' + (dir === "tb" ? "lr" : "tb") + '" aria-pressed="' + (dir === "tb" ? "true" : "false") + '" aria-label="Direction: ' + (dir === "tb" ? "top to bottom" : "left to right") + '" title="' + (dir === "tb" ? "Top to bottom; switch to left to right" : "Left to right; switch to top to bottom") + '">' + (dir === "tb" ? "\u2193" : "\u2192") + "</button>";
    var cluster = R.replayCluster((ui.clusters && ui.clusters[view]) || (R.REPLAY_CLUSTER_DEFAULT && R.REPLAY_CLUSTER_DEFAULT[view]));
    var clusterBtn = '<button type="button" class="rd-rp-btn rd-rp-cluster" data-rp-cluster="' + (cluster === "group" ? "spread" : "group") + '" aria-pressed="' + (cluster === "group" ? "true" : "false") + '" aria-label="Display: ' + cluster + '" title="' + (cluster === "group" ? "Group; switch to spread" : "Spread; switch to group") + '">' + cluster + "</button>";
    /* No /api/v1/replay on this mill: say so; nothing is drawn from other reads. */
    var body = rep.missing ? '<div class="rd-rp-stage rd-rp-empty rd-rp-missing" data-rp-missing="1">This mill does not serve the replay record yet (GET /api/v1/replay). Lines, ticks and spans show once it does.</div>'
      : !rep.known ? '<div class="rd-loading">Loading COLLAB\u2026</div>' : stageHtml(rep, view);
    return '<section class="rd-replay rv-' + view + " rd-dir-" + dir + " rd-cluster-" + cluster + '" data-rp-stage="1" data-rp-subtab="' + view + '" data-rp-dirnow="' + dir + '" data-rp-cluster-now="' + cluster + '">' +
      '<div class="rd-rp-bar">' +
      '<button type="button" class="rd-rp-btn rd-rp-go" data-rp-play="1" aria-label="Play">\u25b6</button>' +
      '<button type="button" class="rd-rp-btn" data-rp-step="1" aria-label="Next event" title="Step to the next event">\u23ed</button>' +
      '<span class="rd-rp-clock" data-rp-clock="1"></span>' +
      '<span class="rd-time-range" role="group" aria-label="Rows in the window">' + counts + "</span>" +
      '<span class="rd-time-range" role="group" aria-label="Replay speed">' + speeds + "</span>" +
      '<span class="rd-rp-rate" data-rp-rate="1">' + h(speedText(rep, ui.speed)) + "</span>" + legendHtml() +
      dirBtn + clusterBtn + '<button type="button" class="rd-rp-btn rd-rp-full" data-rp-full="1" aria-label="Full screen" aria-pressed="' + (ui.full ? "true" : "false") + '" title="' + (ui.full ? "Leave full screen (Esc)" : "Full screen") + '">' + (ui.full ? "\u2715" : "\u26f6") + "</button></div>" +
      '<div class="rd-rp-top">' + overviewHtml(rep) + '<span class="rd-rp-span" data-rp-span="1" aria-live="polite"></span></div>' +
      body + '<div id="rd-rp-tip" class="rd-rp-tip" role="tooltip" hidden></div></section>';
  }

  var SCOPE_TEXT = {
    desks: "", todo: "grouped by state across the roster", mail: "grouped by who they wait on, oldest first",
    priorities: "one column per desk \u00b7 ranks are 1-based, ord on hover", score: "grouped by impact \u00b7 desks are rows \u00b7 platform scores only",
    collab: "the focused desks\u2019 activity, replayed"
  };
  /* The time range lives on the tabs it cuts. TODO, MAIL and COLLAB keep their own time
   * controls (done span, plan window, activity grain) inside the pane they host. */
  var TIMED = { desks: 1, score: 1 };
  function rangeHtml(range) {
    return '<span class="rd-time-range" role="group" aria-label="Time range">' + R.RANGES.map(function (k) {
      return '<button type="button" data-rd-range="' + k + '"' + (k === range ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + (k === "today" ? "Today" : k) + "</button>";
    }).join("") + "</span>";
  }
  function paneHead(tab, base, extra) {
    var sc = base.scope;
    var label = { desks: "DESKS", todo: "TODO", mail: "MAIL", priorities: "PRIORITIES", score: "SCORE", collab: "COLLAB" }[tab];
    var timed = !!TIMED[tab];
    var scope = tab === "desks" ? "" : sc.label + (timed ? " \u00b7 " + R.rangeText(sc.range) : "") + " \u00b7 " + SCOPE_TEXT[tab];
    return '<div class="rd-pane-head">' + (tab === "desks" ? '<button type="button" class="rd-desk-back" data-rd-back="1">Back</button>' : "") +
      "<h2>" + label + "</h2>" + (extra || "") + (timed ? rangeHtml(sc.range) : "") + (scope ? '<span class="rd-pane-scope">' + h(scope) + "</span>" : "") + "</div>";
  }

  /* The head over a tab that hosts its full pane: the scope, and the pane's own view switch. */
  /* One toggle group for the views that show the same data; a view marked alone (TODO's Tree)
   * is its own button beside it. */
  function viewSwitch(views, on) {
    var btn = function (v) {
      var cur = v.key === on;
      return '<button type="button" data-rd-view="' + h(v.key) + '"' + (cur ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + h(v.label) + "</button>";
    };
    var group = (views || []).filter(function (v) { return !v.alone; }), alone = (views || []).filter(function (v) { return v.alone; });
    return (group.length ? '<span class="rd-view-switch" role="group" aria-label="View">' + group.map(btn).join("") + "</span>" : "") +
      alone.map(function (v) { return '<span class="rd-view-switch rd-view-alone">' + btn(v) + "</span>"; }).join("");
  }
  function hostHead(tab, base, views, on) {
    return '<div class="rd-pane-head rd-host-head"><span class="rd-pane-scope">' + h(base.scope.label) + "</span>" + viewSwitch(views, on) + "</div>";
  }

  global.WallRdView = {
    h: h, strip: stripHtml, hero: heroHtml, timed: function (tab) { return !!TIMED[tab]; },
    desksList: desksListHtml, deskDetail: deskDetailHtml, feed: feedHtml, tabScores: tabScoresHtml, paneHead: paneHead, hostHead: hostHead, viewSwitch: viewSwitch,
    todo: todoHtml, mail: mailHtml, priorities: prioritiesHtml, score: scoreHtml, collab: collabHtml,
    replay: replayHtml, kindIcon: kindIcon, replayRows: replayRows, speedText: speedText, tagsHtml: tagsHtml, tagsText: tagsText, replayTip: replayTip, replayLaneTip: replayLaneTip, replayOverflowTip: replayOverflowTip
  };
  global.WALL_UI_DEFAULT_RD_VIEW = "WALL_UI_DEFAULT_RD_VIEW";
})(typeof window !== "undefined" ? window : globalThis);
