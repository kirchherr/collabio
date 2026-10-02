// Native paragraph values are enums, never CSS or HTML supplied by a document.
// Missing values preserve the existing paragraph/heading presentation.
export const OFFICE_PARAGRAPH_VALUES = Object.freeze({
  textAlign: Object.freeze(["left", "center", "right", "justify"]),
  lineSpacing: Object.freeze(["1", "1.15", "1.5", "2"]),
  spacingBefore: Object.freeze([0, 6, 12, 18, 24]),
  spacingAfter: Object.freeze([0, 6, 12, 18, 24]),
});

const domAttributes = Object.freeze({
  textAlign: "data-office-align",
  lineSpacing: "data-office-line-spacing",
  spacingBefore: "data-office-spacing-before",
  spacingAfter: "data-office-spacing-after",
});

export function officeParagraphAttributes(attrs = {}) {
  if (!attrs || typeof attrs !== "object" || Array.isArray(attrs)) throw new TypeError("Invalid paragraph attributes");
  const result = {};
  for (const [key, values] of Object.entries(OFFICE_PARAGRAPH_VALUES)) {
    const value = attrs[key];
    if (value === undefined || value === null) continue;
    if (!values.includes(value)) throw new TypeError("Invalid paragraph attribute");
    result[key] = value;
  }
  return result;
}

export function officeParagraphDOMAttributes(attrs = {}) {
  return Object.fromEntries(Object.entries(officeParagraphAttributes(attrs))
    .map(([key, value]) => [domAttributes[key], String(value)]));
}

export function officeParagraphDescription(attrs = {}) {
  const values = officeParagraphAttributes(attrs);
  const descriptions = [];
  const alignment = { left: "Linksbündig", center: "Zentriert", right: "Rechtsbündig", justify: "Blocksatz" };
  if (values.textAlign !== undefined) descriptions.push(`Ausrichtung: ${alignment[values.textAlign]}`);
  if (values.lineSpacing !== undefined) descriptions.push(`Zeilenabstand: ${values.lineSpacing.replace(".", ",")}`);
  if (values.spacingBefore !== undefined) descriptions.push(`Abstand davor: ${values.spacingBefore} pt`);
  if (values.spacingAfter !== undefined) descriptions.push(`Abstand danach: ${values.spacingAfter} pt`);
  return descriptions;
}
