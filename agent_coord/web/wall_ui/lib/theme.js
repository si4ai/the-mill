/* WALL_UI_LIB_THEME_JS - apply sanitized --* css_vars onto :root (Path A).
 * DB knobs css_vars still Cut 6; this applies static/default + stub overlays.
 * SoR: wall-contract; lib/theme.js
 * Marker: WALL_UI_LIB_THEME_JS
 */
(function (global) {
  "use strict";

  function sanitizeCssVarValue(v) {
    return String(v == null ? "" : v).replace(/;/g, "").replace(/\{/g, "").replace(/\}/g, "").trim();
  }

  function sanitizeCssVars(varsMap) {
    var out = {};
    if (!varsMap || typeof varsMap !== "object") return out;
    Object.keys(varsMap).forEach(function (k) {
      var key = String(k).trim();
      if (key.indexOf("--") !== 0) return;
      var val = sanitizeCssVarValue(varsMap[k]);
      if (val) out[key] = val;
    });
    return out;
  }

  function cssVarsStyleAttr(varsMap) {
    var clean = sanitizeCssVars(varsMap);
    return Object.keys(clean).map(function (k) { return k + ":" + clean[k]; }).join(";");
  }

  function applyCssVars(varsMap, el) {
    var clean = sanitizeCssVars(varsMap);
    if (typeof document === "undefined") return clean;
    el = el || document.documentElement;
    Object.keys(clean).forEach(function (k) {
      try { el.style.setProperty(k, clean[k]); } catch (e) {}
    });
    return clean;
  }

  function themeContract() {
    return {
      marker: "WALL_UI_LIB_THEME",
      stylesheet: "lib/theme.css",
      apply_fn: "wallApplyCssVars",
      sanitize: "--* only; strip ;{}",
      schema_migrated: false,
      path: "A"
    };
  }

  global.wallSanitizeCssVars = sanitizeCssVars;
  global.wallCssVarsStyleAttr = cssVarsStyleAttr;
  global.wallApplyCssVars = applyCssVars;
  global.wallThemeContract = themeContract;
  global.WALL_UI_LIB_THEME_JS = "WALL_UI_LIB_THEME_JS";
})(typeof window !== "undefined" ? window : globalThis);
