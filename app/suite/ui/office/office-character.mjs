// Inert native mark attributes. Presentation is a fixed CSS allowlist.
export const OFFICE_FONT_SIZES = Object.freeze([8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48]);
export const OFFICE_FONT_FAMILIES = Object.freeze({
  sans: "Sans Serif", serif: "Serif", mono: "Monospace",
});
export const OFFICE_TEXT_COLORS = Object.freeze({
  black: "Schwarz", slate: "Schiefergrau", red: "Rot", orange: "Dunkelorange",
  green: "Grün", teal: "Petrol", blue: "Blau", purple: "Violett",
});
export const OFFICE_HIGHLIGHT_COLORS = Object.freeze({
  yellow: "Gelb", lime: "Hellgrün", cyan: "Hellblau", pink: "Rosa", lavender: "Lavendel", gray: "Grau",
});
export const OFFICE_CHARACTER_VALUES = Object.freeze({
  fontFamily: Object.freeze(Object.keys(OFFICE_FONT_FAMILIES)),
  fontSize: OFFICE_FONT_SIZES, textColor: Object.freeze(Object.keys(OFFICE_TEXT_COLORS)),
  highlightColor: Object.freeze(Object.keys(OFFICE_HIGHLIGHT_COLORS)),
});
export const OFFICE_STYLE_CHARACTER_VALUES = Object.freeze({
  fontFamily: OFFICE_CHARACTER_VALUES.fontFamily,
  fontSize: OFFICE_CHARACTER_VALUES.fontSize,
  textColor: OFFICE_CHARACTER_VALUES.textColor,
});

const domNames = Object.freeze({
  fontFamily: "data-office-font-family", fontSize: "data-office-font-size", textColor: "data-office-text-color",
  highlightColor: "data-office-highlight-color",
});

export function officeCharacterAttributes(attrs) {
  if (!attrs || typeof attrs !== "object" || Array.isArray(attrs) ||
      Object.keys(attrs).some((key) => !Object.hasOwn(OFFICE_CHARACTER_VALUES, key))) throw new TypeError("Invalid character attributes");
  const result = {};
  for (const [key, values] of Object.entries(OFFICE_CHARACTER_VALUES)) {
    const value = attrs[key];
    if (value === undefined || value === null) continue; // Only browser defaults; server rejects null.
    if (!values.includes(value)) throw new TypeError("Invalid character attribute");
    result[key] = value;
  }
  return result;
}

export function officeCharacterDOMAttributes(attrs) {
  const result = {};
  for (const [key, value] of Object.entries(officeCharacterAttributes(attrs))) {
    result[domNames[key]] = String(value);
  }
  return result;
}

export function officeCharacterDescription(attrs) {
  const values = officeCharacterAttributes(attrs);
  return [values.fontFamily === undefined ? null : `Schriftart: ${OFFICE_FONT_FAMILIES[values.fontFamily]}`,
    values.fontSize === undefined ? null : `Schriftgröße: ${values.fontSize} pt`,
    values.textColor === undefined ? null : `Textfarbe: ${OFFICE_TEXT_COLORS[values.textColor]}`,
    values.highlightColor === undefined ? null : `Hervorhebung: ${OFFICE_HIGHLIGHT_COLORS[values.highlightColor]}`].filter(Boolean).join("; ");
}
