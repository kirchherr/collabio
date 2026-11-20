import { expect, test } from "@playwright/test";

import {
  OFFICE_PARAGRAPH_VALUES, officeParagraphAttributes, officeParagraphDescription, officeParagraphDOMAttributes,
} from "../office-paragraph.mjs";

test("paragraph indentation exposes only bounded print-safe values", () => {
  expect(OFFICE_PARAGRAPH_VALUES.indentLeft).toEqual([0, 18, 36, 54, 72]);
  expect(OFFICE_PARAGRAPH_VALUES.indentRight).toEqual([0, 18, 36, 54, 72]);
  expect(OFFICE_PARAGRAPH_VALUES.specialIndent).toEqual(["none", "firstLine18", "firstLine36", "hanging18", "hanging36"]);
  const attrs = { indentLeft: 54, indentRight: 36, specialIndent: "hanging18" };
  expect(officeParagraphAttributes(attrs)).toEqual(attrs);
  expect(officeParagraphDOMAttributes(attrs)).toEqual({
    "data-office-indent-left": "54",
    "data-office-indent-right": "36",
    "data-office-special-indent": "hanging18",
  });
  expect(officeParagraphDescription(attrs)).toEqual([
    "Einzug links: 54 pt", "Einzug rechts: 36 pt", "Sondereinzug: Hängend 18 pt",
  ]);
  for (const [key, value] of [["indentLeft", "54"], ["indentRight", 18.5], ["specialIndent", "18pt"]]) {
    expect(() => officeParagraphAttributes({ [key]: value })).toThrow();
  }
});
