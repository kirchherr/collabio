// Bounded, document-local semantic objects. Nothing here evaluates source text,
// resolves a URL, or mutates the document while producing derived views.
export const OFFICE_FIELD_LIMIT = 50;
export const OFFICE_SOURCE_LIMIT = 100;
export const OFFICE_NOTE_LIMIT = 200;

const idPattern = /^[a-z][a-z0-9-]{0,47}$/;
const opaquePatterns = {
  note: /^note-[a-f0-9]{24}$/,
  source: /^source-[a-f0-9]{24}$/,
  equation: /^equation-[a-f0-9]{24}$/,
};
const clean = (value, maximum, required = false) => {
  if (typeof value !== "string" || value.length > maximum || (required && (!value.trim() || value !== value.trim())) ||
      [...value].some((character) => character.charCodeAt(0) < 32 || (character.charCodeAt(0) >= 127 && character.charCodeAt(0) <= 159))) {
    throw new Error("Invalid semantic text");
  }
  return value;
};

export function officeDocumentFields(value = []) {
  if (!Array.isArray(value) || value.length > OFFICE_FIELD_LIMIT) throw new Error("Invalid document fields");
  const keys = new Set();
  return value.map((field) => {
    if (!field || Object.keys(field).sort().join(",") !== "key,label,value" || !idPattern.test(field.key) || keys.has(field.key)) throw new Error("Invalid document field");
    keys.add(field.key);
    return { key: field.key, label: clean(field.label, 64, true), value: clean(field.value, 1000) };
  });
}

export function officeCitationSources(value = []) {
  if (!Array.isArray(value) || value.length > OFFICE_SOURCE_LIMIT) throw new Error("Invalid citation sources");
  const ids = new Set();
  return value.map((source) => {
    if (!source || Object.keys(source).sort().join(",") !== "author,id,locator,title,year" || !opaquePatterns.source.test(source.id) || ids.has(source.id)) throw new Error("Invalid citation source");
    ids.add(source.id);
    return { id: source.id, author: clean(source.author, 200), title: clean(source.title, 500, true), year: clean(source.year, 20), locator: clean(source.locator, 1000) };
  });
}

export function officeSemanticInventory(document) {
  const fields = officeDocumentFields(document?.attrs?.documentFields || []);
  const sources = officeCitationSources(document?.attrs?.citationSources || []);
  const headings = [], notes = [], citations = [], equations = [], references = [];
  const fieldMap = new Map(fields.map((field) => [field.key, field]));
  const sourceMap = new Map(sources.map((source) => [source.id, source]));
  let footnote = 0, endnote = 0;
  const noteIds = new Set(), equationIds = new Set(), generated = new Set();
  const textOf = (node) => (node?.content || []).map((child) => child.type === "text" ? child.text : "").join("").trim();
  const walk = (node) => {
    if (node?.type === "heading") headings.push({ level: node.attrs.level, text: textOf(node) || "Unbenannte Überschrift" });
    if (node?.type === "documentField") {
      const attrs = officeFieldAttributes(node.attrs, fieldMap), field = attrs.field;
      references.push({ kind: "field", id: attrs.key, label: field?.label || attrs.key, broken: !field });
    }
    if (node?.type === "noteReference") {
      const attrs = officeNoteAttributes(node.attrs);
      if (noteIds.has(attrs.id) || noteIds.size >= OFFICE_NOTE_LIMIT) throw new Error("Duplicate or excessive note");
      noteIds.add(attrs.id);
      const number = attrs.kind === "footnote" ? ++footnote : ++endnote;
      notes.push({ ...attrs, number });
      references.push({ kind: attrs.kind, id: attrs.id, label: attrs.text, number, broken: false });
    }
    if (node?.type === "citationReference") {
      const attrs = officeCitationAttributes(node.attrs, sourceMap), source = attrs.source;
      citations.push({ ...attrs, broken: !source });
      references.push({ kind: "citation", id: attrs.sourceId, label: source?.title || attrs.sourceId, broken: !source });
    }
    if (node?.type === "equation") {
      const attrs = officeEquationAttributes(node.attrs);
      if (equationIds.has(attrs.id) || equationIds.size >= 100) throw new Error("Duplicate or excessive equation");
      equationIds.add(attrs.id);
      const item = { ...attrs, number: equations.length + 1 };
      equations.push(item); references.push({ kind: "equation", id: item.id, label: item.alt, number: item.number, broken: false });
    }
    if (["tableOfContents", "bibliography", "referenceIndex"].includes(node?.type)) {
      if (generated.has(node.type)) throw new Error("Duplicate generated structure");
      generated.add(node.type);
    }
    for (const child of node?.content || []) walk(child);
  };
  walk(document);
  return { fields, fieldMap, sources, sourceMap, headings, notes, citations, equations, references };
}

export function officeFieldAttributes(attrs, fields) {
  if (!attrs || Object.keys(attrs).join(",") !== "key" || !idPattern.test(attrs.key)) throw new Error("Invalid document field reference");
  const field = fields instanceof Map ? fields.get(attrs.key) : officeDocumentFields(fields).find((entry) => entry.key === attrs.key);
  return { key: attrs.key, field: field || null, value: field?.value ?? `⟦Fehlendes Feld: ${attrs.key}⟧` };
}

export function officeNoteAttributes(attrs) {
  if (!attrs || Object.keys(attrs).sort().join(",") !== "id,kind,text" || !opaquePatterns.note.test(attrs.id) || !["footnote", "endnote"].includes(attrs.kind)) throw new Error("Invalid note");
  return { id: attrs.id, kind: attrs.kind, text: clean(attrs.text, 2000, true) };
}

export function officeCitationAttributes(attrs, sources) {
  if (!attrs || Object.keys(attrs).sort().join(",") !== "locator,sourceId" || !opaquePatterns.source.test(attrs.sourceId)) throw new Error("Invalid citation");
  const locator = clean(attrs.locator, 100).trim();
  const source = sources instanceof Map ? sources.get(attrs.sourceId) : officeCitationSources(sources).find((entry) => entry.id === attrs.sourceId);
  return { sourceId: attrs.sourceId, locator, source: source || null };
}

export function officeEquationAttributes(attrs) {
  if (!attrs || Object.keys(attrs).sort().join(",") !== "alt,id,source" || !opaquePatterns.equation.test(attrs.id)) throw new Error("Invalid equation");
  return { id: attrs.id, source: clean(attrs.source, 1000, true), alt: clean(attrs.alt, 500, true) };
}

export function officeCitationLabel(source, locator = "") {
  if (!source) return "[Quelle fehlt]";
  const author = source.author || source.title;
  return `[${author}${source.year ? `, ${source.year}` : ""}${locator ? `, ${locator}` : ""}]`;
}

export function officeBibliographyLabel(source) {
  return [source.author, source.year, source.title, source.locator].filter(Boolean).join(". ");
}

export function officeOpaqueId(prefix, cryptoObject = globalThis.crypto) {
  const bytes = new Uint8Array(12); cryptoObject.getRandomValues(bytes);
  return `${prefix}-${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}
