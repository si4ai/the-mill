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
    return '<span class="rd-rp-legend" aria-label="Kinds">' + ["mail", "todo", "hold", "wake", "doing", "score"].map(function (k) {
      return '<span>' + kindIcon(k) + h(KIND_WORD[k]) + "</span>";
    }).join("") + "</span>";
  }
  var WIN_WORD = { hour: "1 hour", day: "1 day", week: "1 week" };
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
  function replayRow(r, fresh) {
    var read = r.read && r.read.length ? '<span class="rd-dim" title="' + h("opened by " + r.read.join(", ")) + '">opened</span>' : "";
    return '<li class="rd-rp-row k-' + h(r.kind) + (r.outside ? " cross" : "") + (fresh ? " rd-fx-in" : "") + '" data-rp="' + h(r.key) + '" data-k="' + h(r.kind) + '" data-act="' + h(r.act) + '" data-dir="' + h(r.dir || "out") + '">' +
      '<time>' + h(clock(r.at)) + "</time>" + kindIcon(r.kind) +
      '<span class="rd-rp-s">' + r.parts.map(partHtml).join(" ") + read + "</span></li>";
  }
  function replayRows(rows, fresh) {
    return rows.map(function (r) { return replayRow(r, fresh && fresh[r.key]); }).join("");
  }
  function speedText(win, speed) {
    var s = Math.round(R.REPLAY_PLAY_MS / 1000 / (speed || 1));
    return (WIN_WORD[win] || win) + " in " + (s >= 60 && s % 60 === 0 ? (s / 60) + " min" : s + "s");
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
  /* The trace strip: one EKG line of row density over the window, drawn twice. The dim copy is
   * what is still to come; the lit copy is clipped to the playhead, so the sweep reveals it. A
   * thin lane under the line takes the colour of each bucket's busiest kind. rd-app moves the
   * clip and the playhead; click or drag on the strip scrubs. */
  var TRACE_W = 1000, TRACE_H = 40, TRACE_BASE = 30;
  function traceHtml(rep) {
    var tr = R.replayTrace(rep, 160), w = TRACE_W / tr.n, pts = [], lane = "";
    for (var i = 0; i < tr.n; i++) {
      var x0 = i * w, c = tr.total[i];
      if (!c) { pts.push(x0.toFixed(1) + "," + TRACE_BASE); continue; }
      var y = TRACE_BASE - 2 - 26 * Math.sqrt(c / tr.peak);
      pts.push(x0.toFixed(1) + "," + TRACE_BASE, (x0 + w * 0.35).toFixed(1) + "," + y.toFixed(1), (x0 + w * 0.6).toFixed(1) + "," + (TRACE_BASE + 3), (x0 + w).toFixed(1) + "," + TRACE_BASE);
      var top = null;
      R.REPLAY_KINDS.forEach(function (k) { if (tr.kinds[k][i] && (top == null || tr.kinds[k][i] > tr.kinds[top][i])) top = k; });
      if (top) lane += '<rect class="k-' + top + '" x="' + x0.toFixed(1) + '" y="' + (TRACE_H - 4) + '" width="' + w.toFixed(1) + '" height="3"/>';
    }
    pts.push(TRACE_W + "," + TRACE_BASE);
    var line = pts.join(" ");
    return '<div class="rd-rp-trace" data-rp-trace="1" role="slider" tabindex="0" aria-label="Replay position" aria-valuemin="0" aria-valuemax="1000" aria-valuenow="1000" title="' + h(plural(rep.rows.length, "row") + ", busiest stretch " + tr.peak) + '">' +
      '<svg viewBox="0 0 ' + TRACE_W + " " + TRACE_H + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<defs><clipPath id="rd-rp-clip"><rect data-rp-clip="1" x="0" y="0" width="' + TRACE_W + '" height="' + TRACE_H + '"/></clipPath></defs>' +
      '<line class="rd-rp-tr-base" x1="0" y1="' + TRACE_BASE + '" x2="' + TRACE_W + '" y2="' + TRACE_BASE + '"/>' +
      '<g class="rd-rp-tr-lane">' + lane + "</g>" +
      '<polyline class="rd-rp-tr-dim" points="' + line + '"/>' +
      '<polyline class="rd-rp-tr-lit" clip-path="url(#rd-rp-clip)" points="' + line + '"/>' +
      '<line class="rd-rp-tr-head" data-rp-head="1" x1="' + TRACE_W + '" y1="0" x2="' + TRACE_W + '" y2="' + TRACE_H + '"/>' +
      "</svg></div>";
  }
  /* ---- Stage: the lanes' pills across the top, one column under each. rd-app drops the six kind
   * icons from a pill into its column as the playhead reaches them, and parks the ones not yet
   * picked up in the receiver's tray. ---- */
  function laneHead(l) {
    var pill = l.t === "desk" ? partHtml({ t: "desk", name: l.name, state: l.state })
      : l.t === "human" ? partHtml({ t: "human", name: l.name })
      : l.t === "cloud" ? partHtml({ t: "cloud", names: l.names && l.names.length ? l.names : ["desks off this pick"] })
      : '<span class="rd-pill rd-office" title="rows no desk sent, like a wake">office</span>';
    return '<div class="rd-rp-lane" data-lane="' + h(l.id) + '">' + pill + '<span class="rd-rp-locks" data-rp-locks="' + h(l.id) + '"></span></div>';
  }
  function stageHtml(rep) {
    var n = rep.lanes.length;
    if (!n) return '<div class="rd-rp-stage rd-rp-empty">No desks on this pick.</div>';
    var cols = rep.lanes.map(function (l) { return '<div class="rd-rp-col" data-col="' + h(l.id) + '"><div class="rd-rp-tray" data-rp-tray="' + h(l.id) + '"></div></div>'; }).join("");
    return '<div class="rd-rp-stage' + (n > 10 ? " rd-rp-many" : "") + '" data-rp-lanes="' + n + '">' +
      '<div class="rd-rp-heads">' + rep.lanes.map(laneHead).join("") + "</div>" +
      '<div class="rd-rp-rain" data-rp-rain="1">' + cols + "</div></div>";
  }
  /* ---- Monitor: the same replay as one heart-monitor trace per lane, in the stage's order,
   * under the shared playhead. Each line rises with the rows the lane sent or received. ---- */
  var MON_W = 1000, MON_H = 24, MON_BASE = 19;
  function laneLine(counts, peak) {
    var w = MON_W / counts.length, pts = [];
    counts.forEach(function (c, i) {
      var x0 = i * w;
      if (!c) { pts.push(x0.toFixed(1) + "," + MON_BASE); return; }
      var y = MON_BASE - 2 - 15 * Math.sqrt(c / Math.max(1, peak));
      pts.push(x0.toFixed(1) + "," + MON_BASE, (x0 + w * 0.35).toFixed(1) + "," + y.toFixed(1), (x0 + w * 0.6).toFixed(1) + "," + (MON_BASE + 2), (x0 + w).toFixed(1) + "," + MON_BASE);
    });
    pts.push(MON_W + "," + MON_BASE);
    return pts.join(" ");
  }
  function monitorHtml(rep) {
    var tr = R.replayLaneTrace(rep, 120);
    if (!rep.lanes.length) return "";
    return '<div class="rd-rp-monitor' + (rep.lanes.length > 10 ? " rd-rp-many" : "") + '" data-rp-monitor="1">' + rep.lanes.map(function (l, i) {
      var c = tr.by[l.id], line = laneLine(c, tr.peak), sum = c.reduce(function (a, x) { return a + x; }, 0), id = "rd-rp-mclip-" + i;
      return '<div class="rd-rp-mlane lt-' + h(l.t) + '" data-rp-mlane="' + h(l.id) + '">' +
        '<span class="rd-rp-mname" title="' + h(l.name + ": " + plural(sum, "row") + " sent or received") + '">' + h(l.name) + "</span>" +
        '<div class="rd-rp-trace rd-rp-mtrace" data-rp-trace="1" role="slider" tabindex="-1" aria-label="' + h(l.name + " activity; replay position") + '" aria-valuemin="0" aria-valuemax="1000" aria-valuenow="1000">' +
        '<svg viewBox="0 0 ' + MON_W + " " + MON_H + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs><clipPath id="' + id + '"><rect data-rp-clip="1" x="0" y="0" width="' + MON_W + '" height="' + MON_H + '"/></clipPath></defs>' +
        '<line class="rd-rp-tr-base" x1="0" y1="' + MON_BASE + '" x2="' + MON_W + '" y2="' + MON_BASE + '"/>' +
        '<polyline class="rd-rp-tr-dim" points="' + line + '"/>' +
        '<polyline class="rd-rp-tr-lit" clip-path="url(#' + id + ')" points="' + line + '"/>' +
        '<line class="rd-rp-tr-head" data-rp-head="1" x1="' + MON_W + '" y1="0" x2="' + MON_W + '" y2="' + MON_H + '"/>' +
        "</svg></div></div>";
    }).join("") + "</div>";
  }
  /* The replay shell. The playhead, the scrubber and the rows are drawn by rd-app as it plays. */
  function replayHtml(rep, blocking, ui) {
    var wins = ["auto", "hour", "day", "week"].map(function (w) {
      var on = w === rep.want, n = w === "auto" ? null : rep.counts[w];
      return '<button type="button" data-rp-win="' + w + '"' + (on ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') +
        (n != null ? ' title="' + h(plural(n, "row") + " in the last " + WIN_WORD[w]) + '"' : ' title="the shortest window with enough to watch"') + ">" +
        (w === "auto" ? "Auto" + (rep.want === "auto" ? " \u00b7 " + rep.window : "") : w.charAt(0).toUpperCase() + w.slice(1)) + "</button>";
    }).join("");
    var speeds = R.REPLAY_SPEEDS.map(function (x) {
      return '<button type="button" data-rp-speed="' + x + '"' + (x === ui.speed ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + (x === 0.25 ? "\u00bc" : x === 0.5 ? "\u00bd" : x) + "x</button>";
    }).join("");
    /* Desks: the stage, scrubbed by the density trace. Activity: one line per desk. One clock. */
    var view = ui.view === "activity" ? "activity" : "desks";
    var body = !rep.known ? '<div class="rd-loading">Loading COLLAB\u2026</div>' :
      (view === "desks" ? stageHtml(rep) : monitorHtml(rep)) +
      '<ol class="rd-rp-list" data-rp-list="1" data-rd-scroll="replay" aria-label="What happened, newest first"></ol>';
    /* The density trace sits on top, over both subtabs; click or drag it to scrub. */
    return '<section class="rd-replay rv-' + view + '" data-rp-stage="1" data-rp-subtab="' + view + '">' +
      '<div class="rd-rp-top">' + traceHtml(rep) + '<span class="rd-rp-span" data-rp-span="1" aria-live="polite"></span></div>' + body + '<div class="rd-rp-bar">' +
      '<button type="button" class="rd-rp-play" data-rp-play="1" aria-label="Play">\u25b6</button>' +
      '<button type="button" class="rd-rp-play" data-rp-step="1" aria-label="Next event" title="Step to the next event">\u23ed</button>' +
      '<span class="rd-rp-clock" data-rp-clock="1"></span>' +
      '<span class="rd-time-range" role="group" aria-label="Replay window">' + wins + "</span>" +
      '<span class="rd-time-range" role="group" aria-label="Replay speed">' + speeds + "</span>" +
      '<span class="rd-rp-rate" data-rp-rate="1">' + h(speedText(rep.window, ui.speed)) + "</span>" + legendHtml() +
      '<span class="rd-pane-scope">' + h(plural(rep.rows.length, "row")) + "</span>" +
      '<button type="button" class="rd-rp-play rd-rp-full" data-rp-full="1" aria-label="Full screen" aria-pressed="' + (ui.full ? "true" : "false") + '" title="' + (ui.full ? "Leave full screen (Esc)" : "Full screen") + '">' + (ui.full ? "\u2715" : "\u26f6") + "</button></div></section>" +
      blockingHtml(blocking, ui.blockOpen);
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
  function viewSwitch(views, on) {
    return views && views.length ? '<span class="rd-view-switch" role="group" aria-label="View">' + views.map(function (v) {
      var cur = v.key === on;
      return '<button type="button" data-rd-view="' + h(v.key) + '"' + (cur ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + h(v.label) + "</button>";
    }).join("") + "</span>" : "";
  }
  function hostHead(tab, base, views, on, allWide) {
    var sw = viewSwitch(views, on);
    var note = allWide ? '<span class="rd-pane-scope">Kanban, list and tree side by side \u00b7 picking a card shows it in all three</span>' : "";
    return '<div class="rd-pane-head rd-host-head"><span class="rd-pane-scope">' + h(base.scope.label) + "</span>" + (allWide ? "" : sw) + note + "</div>";
  }

  global.WallRdView = {
    h: h, strip: stripHtml, hero: heroHtml, timed: function (tab) { return !!TIMED[tab]; },
    desksList: desksListHtml, deskDetail: deskDetailHtml, feed: feedHtml, tabScores: tabScoresHtml, paneHead: paneHead, hostHead: hostHead, viewSwitch: viewSwitch,
    todo: todoHtml, mail: mailHtml, priorities: prioritiesHtml, score: scoreHtml, collab: collabHtml,
    replay: replayHtml, kindIcon: kindIcon, replayRows: replayRows, speedText: speedText
  };
  global.WALL_UI_DEFAULT_RD_VIEW = "WALL_UI_DEFAULT_RD_VIEW";
})(typeof window !== "undefined" ? window : globalThis);
