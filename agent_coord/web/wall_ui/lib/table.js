/* WALL_UI_LIB_TABLE - sort / copy / wrap table helpers (Path A).
 * Extract core from board.html sortTable / tableTsv / cellSortVal.
 * SoR: wall-contract; tests/wall
 * Marker: WALL_UI_LIB_TABLE
 */
(function (global) {
  "use strict";

  function cellSortVal(cell) {
    if (!cell) return "";
    var raw = cell.getAttribute && cell.getAttribute("data-sort");
    if (raw != null && raw !== "") return String(raw).trim();
    return String(cell.innerText || "").replace(/\s+/g, " ").trim();
  }

  function sortTable(tbl, spec) {
    if (!tbl || !spec) return false;
    var tbody = tbl.tBodies && tbl.tBodies[0];
    if (!tbody) return false;
    var idx = spec.col;
    var dir = spec.dir === "asc" ? 1 : -1;
    var rows = [];
    for (var i = 0; i < tbody.rows.length; i++) rows.push(tbody.rows[i]);
    rows.sort(function (a, b) {
      var sa = cellSortVal(a.cells[idx]);
      var sb = cellSortVal(b.cells[idx]);
      var na = Number(sa), nb = Number(sb);
      if (sa !== "" && sb !== "" && !isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
      return String(sa).localeCompare(String(sb), undefined, { numeric: true, sensitivity: "base" }) * dir;
    }).forEach(function (r) { tbody.appendChild(r); });
    if (tbl.tHead && tbl.tHead.rows[0]) {
      var heads = tbl.tHead.rows[0].cells;
      for (var h = 0; h < heads.length; h++) {
        heads[h].classList.toggle("sort-asc", spec.dir === "asc" && h === idx);
        heads[h].classList.toggle("sort-desc", spec.dir === "desc" && h === idx);
      }
    }
    return true;
  }

  function tableTsv(tbl) {
    if (!tbl) return "";
    var lines = [];
    for (var r = 0; r < tbl.rows.length; r++) {
      var row = tbl.rows[r];
      var cells = [];
      for (var c = 0; c < row.cells.length; c++) {
        cells.push(String(row.cells[c].innerText || "").replace(/\s+/g, " ").trim());
      }
      lines.push(cells.join("\t"));
    }
    return lines.join("\n");
  }

  function nextSortSpec(cur, col) {
    cur = cur || { col: col, dir: "asc" };
    if (cur.col === col && cur.dir === "desc") return { col: col, dir: "asc" };
    return { col: col, dir: "desc" };
  }

  global.wallCellSortVal = cellSortVal;
  global.wallSortTable = sortTable;
  global.wallTableTsv = tableTsv;
  global.wallNextSortSpec = nextSortSpec;
  global.WALL_UI_LIB_TABLE = "WALL_UI_LIB_TABLE";
})(typeof window !== "undefined" ? window : globalThis);
