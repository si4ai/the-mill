/* WALL_UI_SHELL_EARLY theme FOUC + hash pane sync + wall_perf gate.
 * One script tag runs all three (data-wall-early=all|boot|empty). Legacy kind=theme|hash|perf still work.
 */
(function () {
  var kind = "";
  try {
    var cs = document.currentScript;
    kind = String((cs && cs.getAttribute("data-wall-early")) || "").toLowerCase();
  } catch (e0) { kind = ""; }
  var runAll = (kind === "" || kind === "all" || kind === "boot");
  var runTheme = runAll || kind === "theme";
  var runHash = runAll || kind === "hash";
  var runPerf = runAll || kind === "perf";

  function applyTheme() {
    try {
      /* Auto -> resolve prefers-color-scheme; pref attr keeps choice */
      var p = localStorage.getItem("factory-theme") || "auto";
      if (p !== "light" && p !== "dark") p = "auto";
      var resolved = p;
      if (p === "auto") {
        try {
          /* A single color-scheme on html makes Chrome report that scheme as the OS. */
          var root0 = document.documentElement;
          var prevScheme0 = root0.style.colorScheme;
          var prevTheme0 = root0.getAttribute("data-theme");
          root0.removeAttribute("data-theme");
          root0.style.colorScheme = "light dark";
          void root0.offsetWidth;
          resolved = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
          if (prevTheme0) root0.setAttribute("data-theme", prevTheme0);
          if (prevScheme0) root0.style.colorScheme = prevScheme0;
          else root0.style.removeProperty("color-scheme");
        } catch (eM) { resolved = "dark"; }
      }
      document.documentElement.setAttribute("data-theme-pref", p);
      document.documentElement.setAttribute("data-theme", resolved);
    } catch (e) {}
  }

  function applyHash() {
    /* WALL_UI_SHELL_BOOT sync pane/strip/subnav from hash before defer boot.js. */
    try {
      if (!document.querySelector || !document.querySelector(".pane")) return false;
      var raw = String(location.hash || "").replace(/^#/, "").split(/[\/?&]/)[0].toLowerCase();
      if (raw === "todo") raw = "jobs";
      var paneMap = {
        session: "pane-session", floor: "pane-floor", jobs: "pane-todo",
        score: "pane-score", mail: "pane-mail", guide: "pane-guide",
        glossary: "pane-glossary", admin: "pane-admin", wire: "pane-wire"
      };
      var paneId = paneMap[raw] || "pane-session";
      var panes = document.querySelectorAll(".pane");
      for (var i = 0; i < panes.length; i++) panes[i].classList.toggle("on", panes[i].id === paneId);
      var stripKey = ({ floor: 1, jobs: 1, score: 1, mail: 1 }[raw] ? raw : "session");
      var stripMap = {
        session: "strip-here", floor: "strip-floor", jobs: "strip-todo",
        score: "strip-score", mail: "strip-mail"
      };
      var sid = stripMap[stripKey] || "strip-here";
      var kpis = document.querySelectorAll(".strip .kpi");
      for (var j = 0; j < kpis.length; j++) {
        kpis[j].classList.add("strip-nav");
        kpis[j].classList.toggle("on", kpis[j].id === sid);
      }
      var forKey = stripKey === "jobs" ? "jobs" : stripKey;
      var sets = document.querySelectorAll("#subnav .subnav-set");
      for (var k = 0; k < sets.length; k++) {
        var f = sets[k].getAttribute("data-for");
        if (f) sets[k].hidden = (f !== forKey);
      }
      var hint = document.getElementById("howto-card");
      if (hint) {
        var hintOn = false;
        try { hintOn = localStorage.getItem("factory-howto") === "on"; } catch (e) {}
        hint.hidden = !hintOn;
      }
      return true;
    } catch (eH) { return false; }
  }

  function scheduleHash() {
    if (applyHash()) return;
    /* Head tag runs before panes exist; run again at interactive (before deferred boot.js). */
    if (document.readyState === "loading") {
      document.addEventListener("readystatechange", function onrs() {
        if (document.readyState === "interactive" || document.readyState === "complete") {
          document.removeEventListener("readystatechange", onrs);
          applyHash();
        }
      });
    } else {
      applyHash();
    }
  }

  function applyPerf() {
    /* WALL_UI_PERF_GATE */
    try {
      var q = new URLSearchParams(location.search || "");
      var v = String(q.get("wall_perf") || "").trim().toLowerCase();
      var on = (v === "1" || v === "on" || v === "true" || v === "yes");
      if (!on) {
        var ls = String(localStorage.getItem("wall_perf") || "").trim().toLowerCase();
        on = (ls === "1" || ls === "on" || ls === "true" || ls === "yes");
      }
      if (!on) return;
      var s = document.createElement("script");
      s.src = "/lib/perf.js?v=wow164";
      document.write(s.outerHTML);
    } catch (e) {}
  }

  if (runTheme) applyTheme();
  if (runPerf) applyPerf();
  if (runHash) {
    if (kind === "hash") applyHash();
    else scheduleHash();
  }
})();
