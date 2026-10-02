// Inert native mark attributes. Presentation is a fixed CSS allowlist.
export const OFFICE_FONT_SIZES = Object.freeze([8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48]);
export const OFFICE_TEXT_COLORS = Object.freeze({
  black: "Schwarz", slate: "Schiefergrau", red: "Rot", orange: "Dunkelorange",
  green: "Grün", teal: "Petrol", blue: "Blau", purple: "Violett",
});
export const OFFICE_CHARACTER_VALUES = Object.freeze({
  fontSize: OFFICE_FONT_SIZES, textColor: Object.freeze(Object.keys(OFFICE_TEXT_COLORS)),
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
    result[key === "fontSize" ? "data-office-font-size" : "data-office-text-color"] = String(value);
  }
  return result;
}

export function officeCharacterDescription(attrs) {
  const values = officeCharacterAttributes(attrs);
  return [values.fontSize === undefined ? null : `Schriftgröße: ${values.fontSize} pt`,
    values.textColor === undefined ? null : `Textfarbe: ${OFFICE_TEXT_COLORS[values.textColor]}`].filter(Boolean).join("; ");
}
