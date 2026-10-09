import { test, expect } from "@playwright/test";

import {
  OFFICE_PARAGRAPH_VALUES, officeParagraphAttributes, officeParagraphDescription, officeParagraphDOMAttributes,
} from "../office-paragraph.mjs";
import { officeStyles } from "../office-styles.mjs";

test("paragraph pagination accepts only explicit boolean values and inert DOM attributes", () => {
  expect(OFFICE_PARAGRAPH_VALUES.keepWithNext).toEqual([false, true]);
  const attrs = { keepWithNext: true, keepLines: true, pageBreakBefore: false };
  expect(officeParagraphAttributes(attrs)).toEqual(attrs);
  expect(officeParagraphDOMAttributes(attrs)).toEqual({
    "data-office-keep-with-next": "true",
    "data-office-keep-lines": "true",
    "data-office-page-break-before": "false",
  });
  expect(officeParagraphDescription(attrs)).toEqual([
    "Mit nächstem Absatz: zusammenhalten", "Zeilen: zusammenhalten", "Seitenumbruch davor: nein",
  ]);
  expect(officeParagraphAttributes({ pageBreakBefore: null })).toEqual({});
  for (const [key, value] of [["keepWithNext", 1], ["keepLines", "true"]]) {
    expect(() => officeParagraphAttributes({ [key]: value })).toThrow();
  }
  expect(officeStyles([{ id: "chapter", name: "Kapitel", paragraph: attrs, character: {} }])[0].paragraph).toEqual(attrs);
});
