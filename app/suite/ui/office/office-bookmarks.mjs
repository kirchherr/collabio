import { officeFigureFragment, officeFigureInventory } from "./office-figures.mjs";

export const OFFICE_BOOKMARK_LIMIT = 100;
export const OFFICE_BOOKMARK_LABEL_MAX = 64;

const identifier = /^[a-z][a-z0-9-]{0,47}$/u;
const forbiddenLabel = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u;

export function officeBookmarkId(value) {
  if (typeof value !== "string" || !identifier.test(value)) throw new TypeError("Invalid Office bookmark ID");
  return value;
}

export function officeBookmarkLabel(value) {
  if (typeof value !== "string" || value !== value.trim() || !value ||
      Array.from(value).length > OFFICE_BOOKMARK_LABEL_MAX || forbiddenLabel.test(value)) {
    throw new TypeError("Invalid Office bookmark label");
  }
  return value;
}

export function officeBookmarkAttributes(value) {
  if (!value || Object.keys(value).sort().join(",") !== "id,label") throw new TypeError("Invalid Office bookmark");
  return { id: officeBookmarkId(value.id), label: officeBookmarkLabel(value.label) };
}

export function officeCrossReferenceAttributes(value) {
  if (!value || Object.keys(value).join(",") !== "targetId") throw new TypeError("Invalid Office cross-reference");
  return { targetId: officeBookmarkId(value.targetId) };
}

export function officeBookmarkFragment(id) {
  return `office-bookmark-${officeBookmarkId(id)}`;
}

export function officeBookmarkInventory(document) {
  let nodes = 0;
  const entries = [];
  const ids = new Set();
  const labels = new Set();
  const walk = (value, depth = 0) => {
    if (!value || typeof value !== "object" || ++nodes > 10000 || depth > 32) throw new TypeError("Invalid Office bookmark document");
    if (value.type === "bookmark") {
      const attrs = officeBookmarkAttributes(value.attrs);
      const folded = attrs.label.toLowerCase();
      if (ids.has(attrs.id) || labels.has(folded) || entries.length >= OFFICE_BOOKMARK_LIMIT) throw new TypeError("Duplicate Office bookmark");
      ids.add(attrs.id); labels.add(folded); entries.push(attrs);
    }
    for (const child of value.content || []) walk(child, depth + 1);
  };
  walk(document);
  return entries;
}

export function officeReferenceInventory(document) {
  const bookmarks = officeBookmarkInventory(document).map((entry) => ({
    ...entry, kind: "bookmark", fragment: officeBookmarkFragment(entry.id),
  }));
  const figures = officeFigureInventory(document).map((entry) => ({
    ...entry, fragment: officeFigureFragment(entry.id),
  }));
  const ids = new Set();
  for (const entry of [...bookmarks, ...figures]) {
    if (ids.has(entry.id)) throw new TypeError("Duplicate Office reference target");
    ids.add(entry.id);
  }
  return [...bookmarks, ...figures];
}

export function officeBookmarkDescription(value) {
  const attrs = officeBookmarkAttributes(value);
  return `Lesezeichen: ${attrs.label}`;
}

export function officeCrossReferenceDescription(value, targets = null) {
  const attrs = officeCrossReferenceAttributes(value);
  if (targets === null) return `Querverweis: ${attrs.targetId}`;
  const target = targets.find((entry) => entry.id === attrs.targetId);
  return target ? `Querverweis: ${target.label}` : `Querverweis: Ziel nicht verfügbar (${attrs.targetId})`;
}
