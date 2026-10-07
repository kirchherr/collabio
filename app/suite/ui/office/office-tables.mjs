const tableIdentifier = /^table-[a-f0-9]{24}$/u;
const forbiddenCaption = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u;

export const OFFICE_TABLE_CAPTION_MAX = 1000;
export const OFFICE_NUMBERED_TABLE_LIMIT = 100;
export const OFFICE_TABLE_CELL_FILLS = ["gray", "blue", "green", "yellow", "red"];
export const OFFICE_TABLE_CELL_VERTICAL_ALIGNMENTS = ["middle", "bottom"];

export function officeTableCellAttributes(value = {}) {
  if (Object.entries(value).some(([key, entry]) =>
    !["colspan", "rowspan", "colwidth", "background", "verticalAlign"].includes(key) && entry != null)) {
    throw new TypeError("Invalid Office table cell");
  }
  if (!value || !Number.isInteger(value.colspan ?? 1) || !Number.isInteger(value.rowspan ?? 1) ||
      (value.colspan ?? 1) < 1 || (value.colspan ?? 1) > 20 ||
      (value.rowspan ?? 1) < 1 || (value.rowspan ?? 1) > 200 || value.colwidth != null ||
      (value.background != null && !OFFICE_TABLE_CELL_FILLS.includes(value.background)) ||
      (value.verticalAlign != null && !OFFICE_TABLE_CELL_VERTICAL_ALIGNMENTS.includes(value.verticalAlign))) {
    throw new TypeError("Invalid Office table cell");
  }
  const result = { colspan: value.colspan ?? 1, rowspan: value.rowspan ?? 1 };
  if (value.background != null) result.background = value.background;
  if (value.verticalAlign != null) result.verticalAlign = value.verticalAlign;
  return result;
}

export function officeTableCellDOMAttributes(value = {}) {
  const attrs = officeTableCellAttributes(value); const result = {};
  if (attrs.background) result["data-office-cell-fill"] = attrs.background;
  if (attrs.verticalAlign) result["data-office-cell-vertical"] = attrs.verticalAlign;
  return result;
}

export function officeTableCellStyleDescription(value = {}) {
  const attrs = officeTableCellAttributes(value); const result = [];
  if (attrs.background) result.push(`Füllung ${attrs.background}`);
  if (attrs.verticalAlign) result.push(`Vertikal ${attrs.verticalAlign}`);
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
  const keys = Object.keys(value).filter((key) => value[key] != null).sort().join(",");
  if (!keys) return {};
  if (keys !== "caption,tableId" || typeof value.caption !== "string" || !value.caption.trim() ||
      Array.from(value.caption).length > OFFICE_TABLE_CAPTION_MAX || forbiddenCaption.test(value.caption)) {
    throw new TypeError("Invalid Office table caption");
  }
  return { caption: value.caption, tableId: officeTableId(value.tableId) };
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
