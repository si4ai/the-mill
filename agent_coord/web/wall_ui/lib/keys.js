/* WALL_UI_LIB_KEYS - per-desk keyboard profiles + customize (Path A).
 * SoR: wall-contract; tests/wall (keyboard)
 * Marker: WALL_UI_LIB_KEYS
 * Storage: localStorage wall-keys:<deskId> = { profile, overrides: { actionId: chord } }
 * Path B: mill prefs keyboard_profile+overrides win when present; else localStorage wall-keys:<deskId>.
 */
(function (global) {
  "use strict";

  var DEFAULT_PROFILE = "windows";
  var PROFILES = ["windows", "brief", "emacs", "vscode", "cursor", "bot", "build"];
  var ACTION_IDS = ["pane.session", "pane.floor", "pane.jobs", "pane.score", "pane.mail", "pane.plan", "pane.admin", "pane.wire", "pane.guide", "pane.prev", "pane.next", "pane.refresh", "focus.filter", "context.new", "ui.help", "ui.cancel", "floor.toggleAgg", "floor.toggleMapTimeline", "mail.next", "mail.prev", "mail.open", "mail.markRead", "profile.cycle"];
  var BROWSER_RESERVED = ["Cmd+N", "Cmd+T", "Cmd+W", "Ctrl+N", "Ctrl+T", "Ctrl+W", "Meta+N", "Meta+T", "Meta+W"];
  var PROFILE_MAPS = {
  "windows": {
    "pane.session": "Alt+1",
    "pane.floor": "Alt+2",
    "pane.jobs": "Alt+3",
    "pane.score": "Alt+4",
    "pane.mail": "Alt+5",
    "pane.plan": "Alt+6",
    "pane.admin": "Alt+7",
    "pane.wire": "Alt+8",
    "pane.guide": "Alt+9",
    "pane.refresh": "F5",
    "pane.prev": "Alt+ArrowLeft",
    "pane.next": "Alt+ArrowRight",
    "focus.filter": "Alt+F",
    "context.new": "Alt+N",
    "ui.help": "?",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "Alt+A",
    "floor.toggleMapTimeline": "Alt+M",
    "mail.next": "Alt+]",
    "mail.prev": "Alt+[",
    "mail.open": "Alt+O",
    "mail.markRead": "Alt+R",
    "profile.cycle": "Alt+`"
  },
  "brief": {
    "pane.session": "Alt+S",
    "pane.floor": "Alt+L",
    "pane.jobs": "Alt+J",
    "pane.score": "Alt+C",
    "pane.mail": "Alt+E",
    "pane.plan": "Alt+P",
    "pane.admin": "Alt+D",
    "pane.wire": "Alt+W",
    "pane.guide": "Alt+G",
    "pane.prev": "Alt",
    "pane.next": "Alt+=",
    "pane.refresh": "Alt+U",
    "focus.filter": "Alt+F",
    "context.new": "Alt+N",
    "ui.help": "Alt+H",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "Alt+A",
    "floor.toggleMapTimeline": "Alt+T",
    "mail.next": "Alt+.",
    "mail.prev": "Alt+,",
    "mail.open": "Alt+O",
    "mail.markRead": "Alt+R",
    "profile.cycle": "Alt+`"
  },
  "emacs": {
    "pane.session": "Ctrl+X 1",
    "pane.floor": "Ctrl+X 2",
    "pane.jobs": "Ctrl+X 3",
    "pane.score": "Ctrl+X 4",
    "pane.mail": "Ctrl+X 5",
    "pane.plan": "Ctrl+X 6",
    "pane.admin": "Ctrl+X 7",
    "pane.wire": "Ctrl+X 8",
    "pane.guide": "Ctrl+X 9",
    "pane.prev": "Ctrl+X Left",
    "pane.next": "Ctrl+X Right",
    "pane.refresh": "Ctrl+X R",
    "focus.filter": "Ctrl+X B",
    "context.new": "Ctrl+X N",
    "ui.help": "Ctrl+H K",
    "ui.cancel": "Ctrl+G",
    "floor.toggleAgg": "Ctrl+X A",
    "floor.toggleMapTimeline": "Ctrl+X M",
    "mail.next": "Ctrl+X ]",
    "mail.prev": "Ctrl+X [",
    "mail.open": "Ctrl+X O",
    "mail.markRead": "Ctrl+X U",
    "profile.cycle": "Ctrl+X P"
  },
  "vscode": {
    "pane.session": "Ctrl+1",
    "pane.floor": "Ctrl+2",
    "pane.jobs": "Ctrl+3",
    "pane.score": "Ctrl+4",
    "pane.mail": "Ctrl+5",
    "pane.plan": "Ctrl+6",
    "pane.admin": "Ctrl+7",
    "pane.wire": "Ctrl+8",
    "pane.guide": "Ctrl+9",
    "pane.prev": "Ctrl+PageUp",
    "pane.next": "Ctrl+PageDown",
    "pane.refresh": "Ctrl+R",
    "focus.filter": "Ctrl+Shift+F",
    "context.new": "Ctrl+Shift+N",
    "ui.help": "Ctrl+P",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "Ctrl+Shift+A",
    "floor.toggleMapTimeline": "Ctrl+Shift+M",
    "mail.next": "Alt+ArrowDown",
    "mail.prev": "Alt+ArrowUp",
    "mail.open": "Enter",
    "mail.markRead": "Ctrl+Shift+U",
    "profile.cycle": "Ctrl+Shift+`"
  },
  "cursor": {
    "pane.session": "Ctrl+1",
    "pane.floor": "Ctrl+2",
    "pane.jobs": "Ctrl+3",
    "pane.score": "Ctrl+4",
    "pane.mail": "Ctrl+5",
    "pane.plan": "Ctrl+6",
    "pane.admin": "Ctrl+7",
    "pane.wire": "Ctrl+8",
    "pane.guide": "Ctrl+9",
    "pane.prev": "Ctrl+PageUp",
    "pane.next": "Ctrl+PageDown",
    "pane.refresh": "Ctrl+R",
    "focus.filter": "Ctrl+Shift+F",
    "context.new": "Ctrl+Shift+N",
    "ui.help": "Ctrl+P",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "Ctrl+Shift+A",
    "floor.toggleMapTimeline": "Ctrl+Shift+M",
    "mail.next": "Alt+ArrowDown",
    "mail.prev": "Alt+ArrowUp",
    "mail.open": "Enter",
    "mail.markRead": "Ctrl+Shift+U",
    "profile.cycle": "Ctrl+Shift+`"
  },
  "bot": {
    "pane.session": "s",
    "pane.floor": "f",
    "pane.jobs": "j",
    "pane.score": "c",
    "pane.mail": "m",
    "pane.plan": "p",
    "pane.admin": "a",
    "pane.wire": "w",
    "pane.guide": "g",
    "pane.prev": "[",
    "pane.next": "]",
    "pane.refresh": "r",
    "focus.filter": "/",
    "context.new": "n",
    "ui.help": "?",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "v",
    "floor.toggleMapTimeline": "t",
    "mail.next": ".",
    "mail.prev": ",",
    "mail.open": "o",
    "mail.markRead": "u",
    "profile.cycle": "`"
  },
  "build": {
    "pane.session": "s",
    "pane.floor": "f",
    "pane.jobs": "j",
    "pane.score": "c",
    "pane.mail": "m",
    "pane.plan": "p",
    "pane.admin": "a",
    "pane.wire": "w",
    "pane.guide": "g",
    "pane.prev": "[",
    "pane.next": "]",
    "pane.refresh": "r",
    "focus.filter": "/",
    "context.new": "n",
    "ui.help": "?",
    "ui.cancel": "Escape",
    "floor.toggleAgg": "v",
    "floor.toggleMapTimeline": "t",
    "mail.next": ".",
    "mail.prev": ",",
    "mail.open": "o",
    "mail.markRead": "u",
    "profile.cycle": "`"
  }
};

  var PANE_ORDER = [
    "pane.session", "pane.floor", "pane.jobs", "pane.score", "pane.mail",
    "pane.plan", "pane.admin", "pane.wire", "pane.guide"
  ];

  var ACTION_LABELS = {
    "pane.session": "Connected",
    "pane.floor": "Floor",
    "pane.jobs": "Jobs",
    "pane.score": "Scorecards",
    "pane.mail": "Mail",
    "pane.plan": "Plan",
    "pane.admin": "Admin",
    "pane.wire": "Wire",
    "pane.guide": "Guide",
    "pane.prev": "Prev pane",
    "pane.next": "Next pane",
    "pane.refresh": "Refresh",
    "focus.filter": "Focus filter",
    "context.new": "New compose/context",
    "ui.help": "Help / keys",
    "ui.cancel": "Cancel / close",
    "floor.toggleAgg": "Floor desk<->workstation",
    "floor.toggleMapTimeline": "Collab between<->timeline",
    "mail.next": "Mail next",
    "mail.prev": "Mail prev",
    "mail.open": "Mail open",
    "mail.markRead": "Mail mark read",
    "profile.cycle": "Cycle key profile"
  };

  function normalizeChord(chord) {
    var raw = String(chord || "").trim();
    if (!raw) return "";
    raw = raw.replace(/C-/g, "Ctrl+").replace(/M-/g, "Alt+");
    var parts = raw.replace(/-/g, "+").split("+").map(function (p) { return p.trim(); }).filter(Boolean);
    if (!parts.length) return "";
    var mods = [];
    var key = "";
    parts.forEach(function (p) {
      var pl = p.toLowerCase();
      if (pl === "ctrl" || pl === "control" || pl === "ctl") mods.push("Ctrl");
      else if (pl === "alt" || pl === "option" || pl === "opt") mods.push("Alt");
      else if (pl === "shift") mods.push("Shift");
      else if (pl === "meta" || pl === "cmd" || pl === "command" || pl === "super" || pl === "win") mods.push("Meta");
      else key = p;
    });
    var order = ["Ctrl", "Alt", "Shift", "Meta"];
    var seen = {};
    mods.forEach(function (m) { seen[m] = 1; });
    var modsSorted = order.filter(function (m) { return seen[m]; });
    if (!key) return modsSorted.join("+");
    var keyOut;
    if (key.length === 1) keyOut = modsSorted.length ? key.toUpperCase() : key.toLowerCase();
    else {
      var kl = key.toLowerCase();
      var named = {
        esc: "Escape", escape: "Escape", return: "Enter", enter: "Enter",
        space: "Space", tab: "Tab", left: "ArrowLeft", right: "ArrowRight",
        up: "ArrowUp", down: "ArrowDown", slash: "/", question: "?",
        pageup: "PageUp", pagedown: "PageDown"
      };
      if (named[kl]) keyOut = named[kl];
      else if (/^f\d+$/i.test(kl)) keyOut = "F" + kl.slice(1);
      else keyOut = key.charAt(0).toUpperCase() + key.slice(1);
    }
    return modsSorted.length ? modsSorted.concat([keyOut]).join("+") : keyOut;
  }

  function storageKey(deskId) {
    return "wall-keys:" + (String(deskId || "").trim() || "anon");
  }

  function loadState(deskId) {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem(storageKey(deskId)) || "null"); } catch (e) { raw = null; }
    var profile = (raw && raw.profile) ? String(raw.profile).toLowerCase() : DEFAULT_PROFILE;
    if (PROFILES.indexOf(profile) < 0) profile = DEFAULT_PROFILE;
    var overrides = {};
    if (raw && raw.overrides && typeof raw.overrides === "object") {
      Object.keys(raw.overrides).forEach(function (aid) {
        if (ACTION_IDS.indexOf(aid) < 0) return;
        var ch = normalizeChord(raw.overrides[aid]);
        if (ch) overrides[aid] = ch;
      });
    }
    return { profile: profile, overrides: overrides };
  }

  function saveState(deskId, state) {
    try {
      localStorage.setItem(storageKey(deskId), JSON.stringify({
        profile: state.profile || DEFAULT_PROFILE,
        overrides: state.overrides || {}
      }));
    } catch (e) {}
  }


  /* WALL_CUT6_WIRE Path B: mill prefs win when present for desk */
  var _millKeysByDesk = {};

  function millStateFor(deskId) {
    var id = String(deskId || "").trim() || "anon";
    return _millKeysByDesk[id] || null;
  }

  function wallKeysApplyMillPrefs(deskId, mill) {
    var id = String(deskId || "").trim() || "anon";
    if (!mill) {
      delete _millKeysByDesk[id];
      return null;
    }
    var profile = String(mill.profile || DEFAULT_PROFILE).toLowerCase();
    if (PROFILES.indexOf(profile) < 0) profile = DEFAULT_PROFILE;
    var overrides = {};
    if (mill.overrides && typeof mill.overrides === "object") {
      Object.keys(mill.overrides).forEach(function (aid) {
        if (ACTION_IDS.indexOf(aid) < 0) return;
        var ch = normalizeChord(mill.overrides[aid]);
        if (ch) overrides[aid] = ch;
      });
    }
    var has = !!(mill.millWins && (mill.profile || Object.keys(overrides).length));
    if (!has && !(mill.profile || Object.keys(overrides).length)) {
      delete _millKeysByDesk[id];
      return null;
    }
    _millKeysByDesk[id] = { profile: profile, overrides: overrides, millWins: true };
    // Optional one-shot migrate localStorage into memory already covered when mill empty.
    return _millKeysByDesk[id];
  }

  function loadStateMerged(deskId) {
    var local = loadState(deskId);
    var mill = millStateFor(deskId);
    if (mill && mill.millWins) {
      return { profile: mill.profile || local.profile, overrides: Object.assign({}, mill.overrides || {}) };
    }
    return local;
  }

  function profileMap(profile) {
    var p = String(profile || DEFAULT_PROFILE).toLowerCase();
    var base = PROFILE_MAPS[p] || PROFILE_MAPS[DEFAULT_PROFILE];
    var out = {};
    Object.keys(base).forEach(function (k) { out[k] = base[k]; });
    return out;
  }

  function effectiveMap(state) {
    var st = state || { profile: DEFAULT_PROFILE, overrides: {} };
    var base = profileMap(st.profile);
    Object.keys(st.overrides || {}).forEach(function (aid) {
      base[aid] = st.overrides[aid];
    });
    return base;
  }

  function findConflicts(actionToChord) {
    var inv = {};
    Object.keys(actionToChord).forEach(function (aid) {
      var ch = actionToChord[aid];
      if (!ch) return;
      if (!inv[ch]) inv[ch] = [];
      inv[ch].push(aid);
    });
    var out = [];
    Object.keys(inv).sort().forEach(function (ch) {
      if (inv[ch].length > 1) out.push({ chord: ch, actions: inv[ch].slice().sort() });
    });
    return out;
  }

  function isBrowserReserved(ch) {
    var n = normalizeChord(ch);
    if (BROWSER_RESERVED.indexOf(n) >= 0) return true;
    if (BROWSER_RESERVED.indexOf(n.replace("Meta+", "Cmd+")) >= 0) return true;
    return false;
  }

  function eventChord(ev) {
    if (!ev) return "";
    var mods = [];
    if (ev.ctrlKey) mods.push("Ctrl");
    if (ev.altKey) mods.push("Alt");
    if (ev.shiftKey) mods.push("Shift");
    if (ev.metaKey) mods.push("Meta");
    var key = ev.key;
    if (key === " ") key = "Space";
    if (key === "Esc") key = "Escape";
    // Ignore pure modifier presses
    if (key === "Control" || key === "Alt" || key === "Shift" || key === "Meta") return "";
    if (key.length === 1) {
      key = mods.length ? key.toUpperCase() : key.toLowerCase();
      // Shift+/ often yields "?" - keep "?"
      if (ev.key === "?" || (ev.shiftKey && ev.code === "Slash")) {
        if (!ev.ctrlKey && !ev.altKey && !ev.metaKey) return "?";
      }
    }
    return mods.length ? mods.concat([key]).join("+") : key;
  }

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if (el.isContentEditable) return true;
    if (el.closest && el.closest("[contenteditable='true']")) return true;
    return false;
  }

  var _prefix = null; // { chord: "Ctrl+X", at: ms }
  var PREFIX_MS = 1200;

  function matchAction(eff, chord) {
    if (!chord) return null;
    // direct
    var aids = Object.keys(eff).filter(function (a) { return eff[a] === chord; });
    if (aids.length) return aids[0];
    return null;
  }

  function matchPrefix(eff, chord) {
    // emacs-style "Ctrl+X 1" stored as "Ctrl+X 1" (space)
    var hits = Object.keys(eff).filter(function (a) {
      var c = eff[a] || "";
      return c.indexOf(chord + " ") === 0;
    });
    return hits.length > 0;
  }

  function resolveDeskId(opts) {
    if (opts && typeof opts.deskId === "function") {
      try { return String(opts.deskId() || ""); } catch (e) { return ""; }
    }
    if (opts && opts.deskId) return String(opts.deskId);
    return "";
  }

  function currentPaneIndex() {
    var on = document.querySelector("nav.tabs button.on[data-tab]");
    var tab = on ? on.getAttribute("data-tab") : "session";
    if (tab === "scorecards") tab = "score";
    var aid = "pane." + tab;
    var i = PANE_ORDER.indexOf(aid);
    return i < 0 ? 0 : i;
  }

  function paintHelp(deskId, state) {
    var box = document.getElementById("wall-keys-help");
    if (!box) return;
    var eff = effectiveMap(state);
    var mapEl = document.getElementById("wall-keys-map");
    var sel = document.getElementById("wall-keys-profile");
    var label = box.querySelector(".wall-keys-profile-label");
    if (label) label.textContent = " | " + state.profile;
    if (sel) {
      if (!sel.options.length) {
        PROFILES.forEach(function (p) {
          var o = document.createElement("option");
          o.value = p; o.textContent = p;
          sel.appendChild(o);
        });
      }
      sel.value = state.profile;
    }
    if (mapEl) {
      var rows = ACTION_IDS.map(function (aid) {
        var ch = eff[aid] || "";
        var over = state.overrides && state.overrides[aid] ? " *" : "";
        return "<tr data-action=\"" + aid + "\"><td>" + (ACTION_LABELS[aid] || aid) +
          "</td><td><code>" + ch + over + "</code></td><td class=\"note\">" + aid + "</td></tr>";
      }).join("");
      mapEl.innerHTML = "<table class=\"wall-keys-table\"><thead><tr><th>Action</th><th>Chord</th><th>id</th></tr></thead><tbody>" +
        rows + "</tbody></table>";
    }
    var actSel = document.getElementById("wall-keys-action");
    if (actSel && !actSel.options.length) {
      ACTION_IDS.forEach(function (aid) {
        var o = document.createElement("option");
        o.value = aid; o.textContent = (ACTION_LABELS[aid] || aid) + " (" + aid + ")";
        actSel.appendChild(o);
      });
    }
    var conflicts = findConflicts(eff);
    var warn = document.getElementById("wall-keys-warn");
    if (warn) {
      if (conflicts.length) {
        warn.hidden = false;
        warn.textContent = "Conflicts: " + conflicts.map(function (c) {
          return c.chord + " -> " + c.actions.join(",");
        }).join("; ");
      } else {
        warn.hidden = true;
        warn.textContent = "";
      }
    }
  }

  function setHelpOpen(on) {
    var box = document.getElementById("wall-keys-help");
    if (!box) return;
    box.hidden = !on;
  }

  function runAction(actionId, api, deskId, state) {
    api = api || {};
    if (actionId.indexOf("pane.") === 0 && actionId !== "pane.prev" && actionId !== "pane.next" && actionId !== "pane.refresh") {
      var name = actionId.slice(5);
      if (typeof api.showTab === "function") api.showTab(name);
      else if (typeof global.showTab === "function") global.showTab(name);
      return;
    }
    if (actionId === "pane.prev" || actionId === "pane.next") {
      var i = currentPaneIndex();
      var j = actionId === "pane.next" ? (i + 1) % PANE_ORDER.length : (i - 1 + PANE_ORDER.length) % PANE_ORDER.length;
      var tab = PANE_ORDER[j].slice(5);
      if (typeof api.showTab === "function") api.showTab(tab);
      else if (typeof global.showTab === "function") global.showTab(tab);
      return;
    }
    if (actionId === "pane.refresh") {
      if (typeof api.refresh === "function") api.refresh();
      else if (typeof global.tick === "function") global.tick();
      return;
    }
    if (actionId === "focus.filter") {
      if (typeof api.openFilter === "function") api.openFilter();
      else {
        var fp = document.getElementById("filter-panel");
        if (fp) fp.hidden = false;
        var btn = document.getElementById("wall-add");
        if (btn) btn.click();
      }
      return;
    }
    if (actionId === "context.new") {
      if (typeof api.openCompose === "function") api.openCompose();
      return;
    }
    if (actionId === "ui.help") {
      var box = document.getElementById("wall-keys-help");
      var open = box && box.hidden;
      if (open) paintHelp(deskId, state);
      setHelpOpen(!!open);
      return;
    }
    if (actionId === "ui.cancel") {
      setHelpOpen(false);
      var panel = document.getElementById("wall-keys-customize-panel");
      if (panel) panel.hidden = true;
      // also close other overlays via Escape handlers already in boot
      return;
    }
    if (actionId === "floor.toggleAgg" && typeof api.toggleFloorAgg === "function") {
      api.toggleFloorAgg(); return;
    }
    if (actionId === "floor.toggleMapTimeline" && typeof api.toggleFloorMapTimeline === "function") {
      api.toggleFloorMapTimeline(); return;
    }
    if (actionId === "mail.next" && typeof api.mailNav === "function") { api.mailNav(1); return; }
    if (actionId === "mail.prev" && typeof api.mailNav === "function") { api.mailNav(-1); return; }
    if (actionId === "mail.open" && typeof api.mailOpen === "function") { api.mailOpen(); return; }
    if (actionId === "mail.markRead" && typeof api.mailMarkRead === "function") { api.mailMarkRead(); return; }
    if (actionId === "profile.cycle") {
      var idx = PROFILES.indexOf(state.profile);
      state.profile = PROFILES[(idx + 1) % PROFILES.length];
      saveState(deskId, state);
      paintHelp(deskId, state);
      return;
    }
  }

  function wallKeysBind(opts) {
    opts = opts || {};
    var api = opts;
    var deskId = resolveDeskId(opts);
    var state = loadStateMerged(deskId);

    // UI wiring
    var dismiss = document.getElementById("wall-keys-help-dismiss");
    if (dismiss) dismiss.addEventListener("click", function () { setHelpOpen(false); });
    var profileSel = document.getElementById("wall-keys-profile");
    if (profileSel) {
      profileSel.addEventListener("change", function () {
        state.profile = profileSel.value;
        saveState(deskId, state);
        paintHelp(deskId, state);
      });
    }
    var customBtn = document.getElementById("wall-keys-customize");
    var customPanel = document.getElementById("wall-keys-customize-panel");
    if (customBtn && customPanel) {
      customBtn.addEventListener("click", function () {
        customPanel.hidden = !customPanel.hidden;
      });
    }
    var resetAll = document.getElementById("wall-keys-reset-all");
    if (resetAll) {
      resetAll.addEventListener("click", function () {
        if (!confirm("Reset all key overrides to profile defaults?")) return;
        state.overrides = {};
        saveState(deskId, state);
        paintHelp(deskId, state);
      });
    }
    var saveOv = document.getElementById("wall-keys-save-override");
    if (saveOv) {
      saveOv.addEventListener("click", function () {
        var aid = (document.getElementById("wall-keys-action") || {}).value;
        var chord = normalizeChord((document.getElementById("wall-keys-chord") || {}).value);
        var warn = document.getElementById("wall-keys-warn");
        if (!aid || !chord) {
          if (warn) { warn.hidden = false; warn.textContent = "Need action + chord"; }
          return;
        }
        if (isBrowserReserved(chord)) {
          if (warn) { warn.hidden = false; warn.textContent = "Browser-reserved chord (Ctrl/Cmd+T/W/N) - not saved"; }
          return;
        }
        var trial = {};
        Object.keys(state.overrides).forEach(function (k) { trial[k] = state.overrides[k]; });
        trial[aid] = chord;
        var eff = effectiveMap({ profile: state.profile, overrides: trial });
        var conflicts = findConflicts(eff).filter(function (c) { return c.actions.indexOf(aid) >= 0; });
        if (conflicts.length) {
          var msg = "Chord conflict: " + conflicts.map(function (c) {
            return c.chord + " -> " + c.actions.join(",");
          }).join("; ") + ". Save anyway (clobber)?";
          if (!confirm(msg)) {
            if (warn) { warn.hidden = false; warn.textContent = msg; }
            return;
          }
        }
        state.overrides = trial;
        saveState(deskId, state);
        paintHelp(deskId, state);
      });
    }
    var resetOne = document.getElementById("wall-keys-reset-one");
    if (resetOne) {
      resetOne.addEventListener("click", function () {
        var aid = (document.getElementById("wall-keys-action") || {}).value;
        if (!aid) return;
        delete state.overrides[aid];
        saveState(deskId, state);
        paintHelp(deskId, state);
      });
    }

    document.addEventListener("keydown", function (ev) {
      // refresh desk id each stroke (badge may change)
      deskId = resolveDeskId(opts);
      state = loadState(deskId);
      var typing = isTypingTarget(ev.target);
      var chord = eventChord(ev);
      if (!chord) return;

      // prefix sequences (emacs Ctrl+X ...)
      var now = Date.now();
      if (_prefix && now - _prefix.at > PREFIX_MS) _prefix = null;
      var eff = effectiveMap(state);
      var full = chord;
      if (_prefix) {
        full = _prefix.chord + " " + (chord.indexOf("+") >= 0 ? chord.split("+").pop() : chord);
      }

      var action = matchAction(eff, full);
      if (!action && !_prefix && matchPrefix(eff, chord)) {
        // start prefix
        _prefix = { chord: chord, at: now };
        ev.preventDefault();
        return;
      }
      if (!action) {
        // also try without prefix clear
        action = matchAction(eff, chord);
      }
      if (!action) {
        if (_prefix) _prefix = null;
        return;
      }
      _prefix = null;

      // while typing: only cancel/help
      if (typing && action !== "ui.cancel" && action !== "ui.help") return;

      // never steal browser reserved even if mapped
      if (isBrowserReserved(chord) || isBrowserReserved(full)) return;

      ev.preventDefault();
      runAction(action, api, deskId, state);
      // reload state if profile.cycle mutated
      state = loadState(deskId);
    }, true);

    // initial paint of profile select options (help closed)
    paintHelp(deskId, state);
    setHelpOpen(false);

    global.WALL_KEYS_API = {
      loadState: function () { return loadState(resolveDeskId(opts)); },
      effectiveMap: function () { return effectiveMap(loadState(resolveDeskId(opts))); },
      storageKey: storageKey,
      normalizeChord: normalizeChord,
      findConflicts: findConflicts,
      paintHelp: function () {
        var d = resolveDeskId(opts);
        paintHelp(d, loadState(d));
        setHelpOpen(true);
      }
    };
  }

  global.wallKeysBind = wallKeysBind;
  global.wallKeysApplyMillPrefs = wallKeysApplyMillPrefs;
  global.wallKeysLoadStateMerged = loadStateMerged;
  global.wallKeysNormalizeChord = normalizeChord;
  global.wallKeysEffectiveMap = function (state) { return effectiveMap(state); };
  global.wallKeysProfileMaps = PROFILE_MAPS;
  global.wallKeysActionIds = ACTION_IDS;
  global.WALL_UI_LIB_KEYS = "WALL_UI_LIB_KEYS";
})(typeof window !== "undefined" ? window : globalThis);
