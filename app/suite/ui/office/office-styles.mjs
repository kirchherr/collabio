// Document-owned, versioned paragraph styles. No CSS, HTML or external references.
import { OFFICE_PARAGRAPH_VALUES, officeParagraphAttributes, officeParagraphDOMAttributes, officeParagraphDescription } from "./office-paragraph.mjs";
import { OFFICE_CHARACTER_VALUES, officeCharacterAttributes, officeCharacterDOMAttributes, officeCharacterDescription } from "./office-character.mjs";

export const OFFICE_STYLE_LIMIT = 20;
export const OFFICE_STYLE_PRESETS = Object.freeze([
  { id: "body", name: "Fließtext", paragraph: { lineSpacing: "1.5", spacingAfter: 6 }, character: { fontSize: 12, textColor: "black" } },
  { id: "title", name: "Titel", paragraph: { spacingBefore: 0, spacingAfter: 18 }, character: { fontSize: 32, textColor: "teal" } },
  { id: "heading", name: "Überschrift", paragraph: { spacingBefore: 18, spacingAfter: 6 }, character: { fontSize: 20, textColor: "teal" } },
]);

export function officeStyles(value = []) {
  const reject = () => { throw new TypeError("Invalid document styles"); };
  if (!Array.isArray(value) || value.length > OFFICE_STYLE_LIMIT) reject();
  const ids = new Set(), names = new Set();
  return value.map((style) => {
    if (!style || typeof style !== "object" || Array.isArray(style) ||
        Object.keys(style).sort().join(",") !== "character,id,name,paragraph" ||
        typeof style.id !== "string" || !/^[a-z][a-z0-9-]{0,47}$/.test(style.id) || ids.has(style.id) ||
        typeof style.name !== "string" || !style.name.length || [...style.name].length > 60 ||
        style.name.trim() !== style.name || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff]/u.test(style.name) || names.has(style.name)) reject();
    for (const [key, values] of [["paragraph", OFFICE_PARAGRAPH_VALUES], ["character", OFFICE_CHARACTER_VALUES]]) {
      const attrs = style[key];
      if (!attrs || typeof attrs !== "object" || Array.isArray(attrs) ||
          Object.entries(attrs).some(([name, entry]) => !Object.hasOwn(values, name) || !values[name].includes(entry))) reject();
    }
    ids.add(style.id); names.add(style.name);
    return { id: style.id, name: style.name, paragraph: officeParagraphAttributes(style.paragraph), character: officeCharacterAttributes(style.character) };
  });
}

export function officeStyleFor(attrs = {}, styles = []) {
  if (attrs.styleId === null || attrs.styleId === undefined) return null;
  const style = styles.find((candidate) => candidate.id === attrs.styleId);
  if (!style) throw new TypeError("Unknown document style");
  return style;
}

export function officeStyledDOMAttributes(attrs = {}, styles = []) {
  const style = officeStyleFor(attrs, styles);
  return { ...officeCharacterDOMAttributes(style?.character || {}),
    ...officeParagraphDOMAttributes({ ...style?.paragraph, ...officeParagraphAttributes(attrs) }) };
}

export function officeStyleDescription(style) {
  return [`Vorlage: ${style.name}`, ...officeParagraphDescription(style.paragraph), officeCharacterDescription(style.character)].filter(Boolean).join(" · ");
}

export function officeTextblockAttributes(attrs = {}) {
  return { ...officeParagraphAttributes(attrs), ...(attrs.styleId == null ? {} : { styleId: attrs.styleId }) };
}

// Comparison expands inherited presentation only for display/identity; original
// canonical saved content and text positions remain untouched.
export function officeStyleComparisonDocument(document) {
  const styles = officeStyles(document.attrs?.styles || []);
  const visit = (entry) => {
    let result = entry;
    if (["paragraph", "heading"].includes(entry.type)) {
      const style = officeStyleFor(entry.attrs, styles);
      if (style) result = { ...entry, attrs: { ...style.paragraph, ...entry.attrs, styleDescription: officeStyleDescription(style) } };
    }
    if (entry.content) {
      const content = entry.content.map(visit);
      // Preserve the established reference contract for every unchanged subtree.
      // Only a bound style or a changed descendant needs a display-only copy.
      if (content.some((child, index) => child !== entry.content[index])) result = { ...result, content };
    }
    return result;
  };
  return visit(document);
}
