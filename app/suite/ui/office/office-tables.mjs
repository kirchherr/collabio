const tableIdentifier = /^table-[a-f0-9]{24}$/u;
const forbiddenCaption = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u;

export const OFFICE_TABLE_CAPTION_MAX = 1000;
export const OFFICE_NUMBERED_TABLE_LIMIT = 100;
export const OFFICE_TABLE_CELL_FILLS = ["gray", "blue", "green", "yellow", "red"];
export const OFFICE_TABLE_CELL_VERTICAL_ALIGNMENTS = ["middle", "bottom"];
export const OFFICE_TABLE_CELL_HORIZONTAL_ALIGNMENTS = ["center", "right"];
export const OFFICE_TABLE_CELL_PADDINGS = ["compact", "spacious"];
export const OFFICE_TABLE_CELL_BORDERS = ["none", "strong"];
export const OFFICE_TABLE_STYLES = ["minimal", "banded", "accent"];
export const OFFICE_TABLE_WIDTHS = ["compact", "wide"];
export const OFFICE_TABLE_ALIGNMENTS = ["center", "right"];
export const OFFICE_TABLE_COLUMN_LAYOUTS = ["first-wide", "first-narrow"];
export const OFFICE_TABLE_FORMULA_ERRORS = ["#BEZUG!", "#DIV/0!", "#ZYKLUS!", "#WERT!", "#LIMIT!"];

export function officeTableFormulaSource(value) {
  if (typeof value !== "string") throw new TypeError("Invalid Office table formula");
  const source = value.trim().replaceAll("$", "").replaceAll(";", ",")
    .replace(/\bSUMME\b/giu, "SUM").replace(/\bMITTELWERT\b/giu, "AVERAGE")
    .replace(/\bANZAHL\b/giu, "COUNT").toUpperCase();
  const identifiers = source.replaceAll("#BEZUG!", "");
  if (!source.startsWith("=") || source.length < 2 || source.length > 256 ||
      !/^=[A-Z0-9#\-+*/().,:! ]+$/u.test(source) || /[#!]/u.test(identifiers)) {
    throw new TypeError("Invalid Office table formula");
  }
  for (const match of identifiers.matchAll(/[A-Z]+/gu)) {
    if (!["SUM", "AVERAGE", "MIN", "MAX", "COUNT"].includes(match[0]) && !/^[A-T]$/u.test(match[0])) {
      throw new TypeError("Invalid Office table formula");
    }
  }
  return source;
}

export function officeTableFormulaResult(value) {
  if (typeof value !== "string" || value.length < 1 || value.length > 64 ||
      (!OFFICE_TABLE_FORMULA_ERRORS.includes(value) && !/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,10})?$/u.test(value))) {
    throw new TypeError("Invalid Office table formula result");
  }
  return value;
}

export function officeTableCellAttributes(value = {}) {
  if (Object.entries(value).some(([key, entry]) =>
    !["colspan", "rowspan", "colwidth", "background", "verticalAlign", "horizontalAlign", "padding", "border", "formula", "formulaResult"].includes(key) && entry != null)) {
    throw new TypeError("Invalid Office table cell");
  }
  if (!value || !Number.isInteger(value.colspan ?? 1) || !Number.isInteger(value.rowspan ?? 1) ||
      (value.colspan ?? 1) < 1 || (value.colspan ?? 1) > 20 ||
      (value.rowspan ?? 1) < 1 || (value.rowspan ?? 1) > 200 || value.colwidth != null ||
      (value.background != null && !OFFICE_TABLE_CELL_FILLS.includes(value.background)) ||
      (value.verticalAlign != null && !OFFICE_TABLE_CELL_VERTICAL_ALIGNMENTS.includes(value.verticalAlign)) ||
      (value.horizontalAlign != null && !OFFICE_TABLE_CELL_HORIZONTAL_ALIGNMENTS.includes(value.horizontalAlign)) ||
      (value.padding != null && !OFFICE_TABLE_CELL_PADDINGS.includes(value.padding)) ||
      (value.border != null && !OFFICE_TABLE_CELL_BORDERS.includes(value.border)) ||
      ((value.formula == null) !== (value.formulaResult == null)) ||
      (value.formula != null && ((value.colspan ?? 1) !== 1 || (value.rowspan ?? 1) !== 1))) {
    throw new TypeError("Invalid Office table cell");
  }
  const result = { colspan: value.colspan ?? 1, rowspan: value.rowspan ?? 1 };
  if (value.background != null) result.background = value.background;
  if (value.verticalAlign != null) result.verticalAlign = value.verticalAlign;
  if (value.horizontalAlign != null) result.horizontalAlign = value.horizontalAlign;
  if (value.padding != null) result.padding = value.padding;
  if (value.border != null) result.border = value.border;
  if (value.formula != null) {
    result.formula = officeTableFormulaSource(value.formula);
    result.formulaResult = officeTableFormulaResult(value.formulaResult);
  }
  return result;
}

export function officeTableCellDOMAttributes(value = {}) {
  const attrs = officeTableCellAttributes(value); const result = {};
  if (attrs.background) result["data-office-cell-fill"] = attrs.background;
  if (attrs.verticalAlign) result["data-office-cell-vertical"] = attrs.verticalAlign;
  if (attrs.horizontalAlign) result["data-office-cell-align"] = attrs.horizontalAlign;
  if (attrs.padding) result["data-office-cell-padding"] = attrs.padding;
  if (attrs.border) result["data-office-cell-border"] = attrs.border;
  if (attrs.formula) {
    result["data-office-cell-formula"] = attrs.formula;
    result["data-office-cell-formula-result"] = attrs.formulaResult;
  }
  return result;
}

export function officeTableCellStyleDescription(value = {}) {
  const attrs = officeTableCellAttributes(value); const result = [];
  if (attrs.background) result.push(`Füllung ${attrs.background}`);
  if (attrs.verticalAlign) result.push(`Vertikal ${attrs.verticalAlign}`);
  if (attrs.horizontalAlign) result.push(`Horizontal ${attrs.horizontalAlign}`);
  if (attrs.padding) result.push(`Innenabstand ${attrs.padding}`);
  if (attrs.border) result.push(`Rahmen ${attrs.border}`);
  return result;
}

export function officeTableGrid(value) {
  const rows = value?.type === "table" ? value.content : null;
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > 200) throw new TypeError("Invalid Office table grid");
  let width = null; let active = [];
  rows.forEach((row, rowIndex) => {
    if (row?.type !== "tableRow" || !Array.isArray(row.content) || row.content.length < 1 || row.content.length > 20) {
      throw new TypeError("Invalid Office table row");
    }
    const occupied = active.map((remaining) => remaining > 0); let column = 0;
    for (const cell of row.content) {
      if (!cell || !["tableCell", "tableHeader"].includes(cell.type)) throw new TypeError("Invalid Office table cell");
      const attrs = officeTableCellAttributes(cell.attrs); while (occupied[column]) column += 1;
      if (column + attrs.colspan > 20 || column + attrs.colspan > (width ?? 20) ||
          Array.from({ length: attrs.colspan }, (_, offset) => occupied[column + offset]).some(Boolean) ||
          rowIndex + attrs.rowspan > rows.length) throw new TypeError("Invalid Office table span");
      for (let offset = 0; offset < attrs.colspan; offset += 1) {
        occupied[column + offset] = true; active[column + offset] = attrs.rowspan;
      }
      column += attrs.colspan;
    }
    const rowWidth = occupied.lastIndexOf(true) + 1;
    if (width == null) width = rowWidth;
    if (rowWidth !== width || occupied.slice(0, width).some((entry) => !entry)) throw new TypeError("Invalid Office table grid");
    active = Array.from({ length: width }, (_, index) => Math.max(0, (active[index] || 0) - 1));
  });
  if (active.some(Boolean)) throw new TypeError("Invalid Office table grid");
  return { rows: rows.length, columns: width };
}

export function officeTableId(value) {
  if (typeof value !== "string" || !tableIdentifier.test(value)) throw new TypeError("Invalid Office table ID");
  return value;
}

export function officeTableFragment(id) {
  return `office-table-${officeTableId(id)}`;
}

export function officeTableAttributes(value = {}) {
  if (!value || Object.entries(value).some(([key, entry]) =>
    !["caption", "tableId", "style", "width", "align", "columns", "captionPosition"].includes(key) && entry != null)) {
    throw new TypeError("Invalid Office table");
  }
  const captioned = value.caption != null || value.tableId != null;
  if (captioned && (typeof value.caption !== "string" || !value.caption.trim() ||
      Array.from(value.caption).length > OFFICE_TABLE_CAPTION_MAX || forbiddenCaption.test(value.caption))) {
    throw new TypeError("Invalid Office table caption");
  }
  if ((value.style != null && !OFFICE_TABLE_STYLES.includes(value.style)) ||
      (value.width != null && !OFFICE_TABLE_WIDTHS.includes(value.width)) ||
      (value.align != null && !OFFICE_TABLE_ALIGNMENTS.includes(value.align)) ||
      (value.columns != null && !OFFICE_TABLE_COLUMN_LAYOUTS.includes(value.columns)) ||
      (value.captionPosition != null && value.captionPosition !== "top")) throw new TypeError("Invalid Office table layout");
  const result = {};
  if (captioned) { result.caption = value.caption; result.tableId = officeTableId(value.tableId); }
  if (value.style != null) result.style = value.style;
  if (value.width != null) result.width = value.width;
  if (value.align != null) result.align = value.align;
  if (value.columns != null) result.columns = value.columns;
  if (value.captionPosition != null) result.captionPosition = value.captionPosition;
  return result;
}

export function officeTableDOMAttributes(value = {}) {
  const attrs = officeTableAttributes(value); const result = {};
  if (attrs.style) result["data-office-table-style"] = attrs.style;
  if (attrs.width) result["data-office-table-width"] = attrs.width;
  if (attrs.align) result["data-office-table-align"] = attrs.align;
  if (attrs.columns) result["data-office-table-columns"] = attrs.columns;
  if (attrs.captionPosition) result["data-office-caption-position"] = attrs.captionPosition;
  return result;
}

export function officeTableLayoutDescription(value = {}) {
  const attrs = officeTableAttributes(value); const result = [];
  if (attrs.style) result.push(`Stil ${attrs.style}`);
  if (attrs.width) result.push(`Breite ${attrs.width}`);
  if (attrs.align) result.push(`Ausrichtung ${attrs.align}`);
  if (attrs.columns) result.push(`Spalten ${attrs.columns}`);
  if (attrs.captionPosition) result.push("Beschriftung oben");
  return result;
}

export function officeTableCellText(value) {
  let nodes = 0; const parts = [];
  const walk = (node, depth = 0) => {
    if (!node || typeof node !== "object" || ++nodes > 10000 || depth > 32) throw new TypeError("Invalid Office table text");
    if (node.type === "text") {
      if (typeof node.text !== "string") throw new TypeError("Invalid Office table text");
      parts.push(node.text); return;
    }
    if (node.type === "hardBreak") parts.push("\n");
    if (node.content != null && !Array.isArray(node.content)) throw new TypeError("Invalid Office table text");
    for (const child of node.content || []) walk(child, depth + 1);
    if (["paragraph", "heading", "listItem", "blockquote", "codeBlock"].includes(node.type)) parts.push(" ");
  };
  walk(value);
  return parts.join("").replace(/\s+/gu, " ").trim();
}

export function officeTableSortInfo(value) {
  const grid = officeTableGrid(value);
  for (const row of value.content) {
    if (row.content.length !== grid.columns || row.content.some((cell) => {
      const attrs = officeTableCellAttributes(cell.attrs);
      return attrs.colspan !== 1 || attrs.rowspan !== 1;
    })) throw new TypeError("Office table sorting requires a simple grid");
  }
  const header = value.content[0].content.every((cell) => cell.type === "tableHeader");
  return { ...grid, header, dataRows: grid.rows - (header ? 1 : 0) };
}

function officeTableSortKey(value, type) {
  const text = officeTableCellText(value);
  if (!text) return { empty: true, value: "" };
  if (type === "text") return { empty: false, value: text.normalize("NFKC").toLowerCase() };
  if (type === "number") {
    if (!/^[+-]?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?$/u.test(text)) throw new TypeError("Invalid Office table number");
    const number = Number(text.replace(",", "."));
    if (!Number.isFinite(number) || Math.abs(number) > 1e15) throw new TypeError("Invalid Office table number");
    return { empty: false, value: number };
  }
  if (type === "date") {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/u.exec(text);
    if (!match) throw new TypeError("Invalid Office table date");
    const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    const stamp = Date.UTC(year, month - 1, day);
    const checked = new Date(stamp);
    if (year < 1000 || year > 9999 || checked.getUTCFullYear() !== year || checked.getUTCMonth() !== month - 1 ||
        checked.getUTCDate() !== day) throw new TypeError("Invalid Office table date");
    return { empty: false, value: stamp };
  }
  throw new TypeError("Invalid Office table sort type");
}

export function sortOfficeTable(value, options) {
  const info = officeTableSortInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "column,direction,type" ||
      !Number.isInteger(options.column) || options.column < 0 || options.column >= info.columns ||
      !["text", "number", "date"].includes(options.type) || !["ascending", "descending"].includes(options.direction) ||
      info.dataRows < 2) throw new TypeError("Invalid Office table sort");
  const start = info.header ? 1 : 0;
  const rows = value.content.slice(start).map((row, index) => ({ row, index,
    key: officeTableSortKey(row.content[options.column], options.type) }));
  rows.sort((left, right) => {
    if (left.key.empty !== right.key.empty) return left.key.empty ? 1 : -1;
    if (left.key.empty) return left.index - right.index;
    const compared = left.key.value < right.key.value ? -1 : left.key.value > right.key.value ? 1 : 0;
    return (options.direction === "descending" ? -compared : compared) || left.index - right.index;
  });
  return { ...value, content: [...(info.header ? [value.content[0]] : []), ...rows.map(({ row }) => row)] };
}

export function officeTableReorderInfo(value) {
  const info = officeTableSortInfo(value);
  const headerColumn = value.content.every((row) => row.content[0].type === "tableHeader");
  return { ...info, headerColumn };
}

function officeTableMoveRange(values, from, to, direction, minimum = 0) {
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < minimum || to <= from || to > values.length ||
      !["before", "after"].includes(direction) ||
      (direction === "before" && from === minimum) || (direction === "after" && to === values.length)) {
    throw new TypeError("Invalid Office table move");
  }
  const result = [...values]; const block = result.splice(from, to - from);
  result.splice(direction === "before" ? from - 1 : from + 1, 0, ...block);
  return result;
}

export function moveOfficeTableRows(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "direction,from,to") {
    throw new TypeError("Invalid Office table row move");
  }
  return { ...value, content: officeTableMoveRange(value.content, options.from, options.to, options.direction,
    info.header ? 1 : 0) };
}

export function moveOfficeTableColumns(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "direction,from,to") {
    throw new TypeError("Invalid Office table column move");
  }
  const minimum = info.headerColumn ? 1 : 0;
  // Validate the range and boundary once before rebuilding every complete row.
  officeTableMoveRange(Array.from({ length: info.columns }), options.from, options.to, options.direction, minimum);
  return { ...value, content: value.content.map((row) => ({ ...row,
    content: officeTableMoveRange(row.content, options.from, options.to, options.direction, minimum) })) };
}

function officeTableDuplicateRange(values, from, to, minimum, maximum) {
  const count = to - from;
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < minimum || to <= from || to > values.length ||
      values.length + count > maximum) throw new TypeError("Invalid Office table duplication");
  return [...values.slice(0, to), ...structuredClone(values.slice(from, to)), ...values.slice(to)];
}

export function duplicateOfficeTableRows(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "from,to") {
    throw new TypeError("Invalid Office table row duplication");
  }
  return { ...value, content: officeTableDuplicateRange(value.content, options.from, options.to,
    info.header ? 1 : 0, 200) };
}

export function duplicateOfficeTableColumns(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "from,to") {
    throw new TypeError("Invalid Office table column duplication");
  }
  const minimum = info.headerColumn ? 1 : 0;
  officeTableDuplicateRange(Array.from({ length: info.columns }), options.from, options.to, minimum, 20);
  return { ...value, content: value.content.map((row) => ({ ...row,
    content: officeTableDuplicateRange(row.content, options.from, options.to, minimum, 20) })) };
}

export function officeTableInventory(document) {
  let nodes = 0;
  const entries = [], ids = new Set();
  const walk = (value, depth = 0) => {
    if (!value || typeof value !== "object" || ++nodes > 10000 || depth > 32) throw new TypeError("Invalid Office table document");
    if (value.type === "table") {
      const attrs = officeTableAttributes(value.attrs);
      if (attrs.tableId != null) {
        if (ids.has(attrs.tableId) || entries.length >= OFFICE_NUMBERED_TABLE_LIMIT) throw new TypeError("Invalid Office table");
        ids.add(attrs.tableId);
        entries.push({ id: attrs.tableId, kind: "table", number: entries.length + 1,
          label: `Tabelle ${entries.length + 1}: ${attrs.caption}` });
      }
    }
    for (const child of value.content || []) walk(child, depth + 1);
  };
  walk(document);
  return entries;
}

export function officeTableCaption(attrs, number) {
  const value = officeTableAttributes(attrs);
  if (value.tableId == null || !Number.isInteger(number) || number < 1 || number > OFFICE_NUMBERED_TABLE_LIMIT) {
    throw new TypeError("Invalid Office table number");
  }
  return `Tabelle ${number}: ${value.caption}`;
}
