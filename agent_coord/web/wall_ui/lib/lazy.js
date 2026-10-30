/* WALL_UI_LIB_LAZY - script/CSS single-flight loader + domain ensure (Wave 2 / #40).
 * Marker: WALL_UI_LIB_LAZY
 */
(function (global) {
  "use strict";

  var pending = {};
  var loaded = {};

  function loadScript(src) {
    src = String(src || "");
    if (!src) return Promise.resolve();
    if (loaded[src]) return Promise.resolve();
    if (pending[src]) return pending[src];
    pending[src] = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = function () {
        loaded[src] = true;
        delete pending[src];
        resolve();
      };
      s.onerror = function () {
        delete pending[src];
        reject(new Error("wallLoadScript failed: " + src));
      };
      (document.head || document.documentElement).appendChild(s);
    });
    return pending[src];
  }

  function loadCss(href) {
    href = String(href || "");
    if (!href) return Promise.resolve();
    if (loaded[href]) return Promise.resolve();
    if (pending[href]) return pending[href];
    var existing = document.querySelector('link[data-wall-lazy="' + href.replace(/"/g, "") + '"]');
    if (existing) {
      loaded[href] = true;
      return Promise.resolve();
    }
    pending[href] = new Promise(function (resolve, reject) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.setAttribute("data-wall-lazy", href);
      link.onload = function () {
        loaded[href] = true;
        delete pending[href];
        resolve();
      };
      link.onerror = function () {
        delete pending[href];
        reject(new Error("wallLoadCss failed: " + href));
      };
      (document.head || document.documentElement).appendChild(link);
    });
    return pending[href];
  }

  /* Root-absolute hrefs: under /project|/station|/role pathname,
   * relative mail/mail.js would resolve to /project/mail/mail.js (404). */
  /* WALL_DOMAIN_PINS_WOW182: all domain JS/CSS root-absolute + tip bust. */
  var DOMAINS = {
    mail: {
      js: "/mail/mail.js?v=wow285",
      css: "/mail/mail.css?v=wow316",
      marker: "WALL_UI_DEFAULT_MAIL",
      modules: ["mailPaint"]
    },
    score: {
      js: "/score/score.js?v=wow322",
      css: "/score/score.css?v=wow319",
      marker: "WALL_UI_DEFAULT_SCORE",
      modules: ["scorePaint"]
    },
    todo: {
      js: "/todo/todo.js?v=wow320",
      css: "/todo/todo.css?v=wow319",
      marker: "WALL_UI_DEFAULT_TODO",
      modules: ["todoPaint"]
    }
  };

  function ensureDomain(name) {
    var d = DOMAINS[String(name || "").toLowerCase()];
    if (!d) return Promise.resolve(null);
    var jsP = global[d.marker]
      ? Promise.resolve()
      : loadScript(d.js);
    var cssP = loadCss(d.css).catch(function () { /* CSS missing is non-fatal */ });
    /* #710: the pane's paint code (split out of boot.js) loads with the pane. */
    var modP = (d.modules || []).map(function (m) { return ensureModule(m); });
    return Promise.all([jsP, cssP].concat(modP)).then(function () { return d.marker; });
  }


  /* Session first-paint split: glossary / floor map / admin invite load on demand. */
  var MODULES = {
    glossary: {
      js: "/glossary/glossary.js?v=wow285",
      marker: "WALL_UI_DEFAULT_GLOSSARY"
    },
    floorMap: {
      js: "/floor/map-paint.js?v=wow319",
      marker: "WALL_UI_DEFAULT_FLOOR_MAP"
    },
    adminInvite: {
      js: "/admin/invite.js?v=wow280",
      marker: "WALL_UI_DEFAULT_ADMIN_INVITE"
    },
    mailPaint: {
      js: "/mail/mail-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_MAIL_PAINT",
      domain: "mail"
    },
    scorePaint: {
      js: "/score/score-paint.js?v=wow322",
      marker: "WALL_UI_DEFAULT_SCORE_PAINT",
      domain: "score"
    },
    floorPaint: {
      js: "/floor/floor-paint.js?v=wow322",
      marker: "WALL_UI_DEFAULT_FLOOR_PAINT",
      with: ["floorMap"]
    },
    todoPaint: {
      js: "/todo/todo-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_TODO_PAINT",
      domain: "todo"
    },
    /* #872 rule-lazy-panes: pane-only code split out of boot.js; each loads on first use. */
    deskPaint: {
      js: "/session/desk-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_DESK_PAINT"
    },
    servicePaint: {
      js: "/session/service-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_SERVICE_PAINT"
    },
    listsPaint: {
      js: "/lists/lists-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_LISTS_PAINT"
    },
    adminMint: {
      js: "/admin/mint-paint.js?v=wow321",
      marker: "WALL_UI_DEFAULT_ADMIN_MINT"
    },
    /* #818 PR C: the doing view (strip, pill, trails). Loads after the first CONNECTED paint. */
    doingPaint: {
      js: "/doing/doing-paint.js?v=wow322",
      css: "/doing/doing.css?v=wow319",
      marker: "WALL_UI_DEFAULT_DOING_PAINT"
    }
  };

  function ensureModule(name) {
    var m = MODULES[String(name || "")];
    if (!m) return Promise.resolve(null);
    /* #710: a module's "with" list loads alongside it (one round trip, not two). */
    var withP = (m.with || []).map(function (w) { return ensureModule(w); });
    /* A module's own CSS loads beside it; a missing sheet is non-fatal. */
    if (m.css) withP.push(loadCss(m.css).catch(function () {}));
    if (global[m.marker]) return Promise.all(withP).then(function () { return m.marker; });
    return Promise.all([loadScript(m.js)].concat(withP)).then(function () { return m.marker; });
  }

  /* #710 pane paint split: boot.js keeps a stub per entry of a split pane.
   * The first call loads the module; its top-level function declarations
   * replace the stubs as globals, and the call is replayed on the real one.
   * A module with a domain is pane code that needs its domain file (mail.js),
   * so the whole domain loads first. Resolves with the real return value; a
   * load failure warns and resolves. */
  function lazyCall(mod, name, stub, args) {
    var m = MODULES[String(mod || "")];
    var load = (m && m.domain) ? ensureDomain(m.domain) : ensureModule(mod);
    return load.then(function () {
      var real = global[name];
      if (typeof real !== "function" || real === stub) {
        throw new Error("wallLazyCall: " + name + " not defined by " + mod);
      }
      return real.apply(global, args);
    }).catch(function (e) {
      try { console.warn("wallLazyCall " + mod + "." + name + ": " + ((e && e.message) || e)); } catch (eW) {}
    });
  }

  global.wallLoadScript = loadScript;
  global.wallLazyCall = lazyCall;
  global.wallLoadCss = loadCss;
  global.wallEnsureDomain = ensureDomain;
  global.wallEnsureModule = ensureModule;
  global.WALL_UI_LIB_LAZY = "WALL_UI_LIB_LAZY";
  global.WALL_UI_LIB_LAZY_DOMAINS = Object.keys(DOMAINS);
  global.WALL_LAZY_MODULES = Object.keys(MODULES);
})(typeof window !== "undefined" ? window : globalThis);
