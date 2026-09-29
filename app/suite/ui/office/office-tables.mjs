const tableIdentifier = /^table-[a-f0-9]{24}$/u;
const forbiddenCaption = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u;

export const OFFICE_TABLE_CAPTION_MAX = 1000;
export const OFFICE_NUMBERED_TABLE_LIMIT = 100;

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
