import { expect, test } from "@playwright/test";
import { officeStyles, officeStyledDOMAttributes, officeStyleComparisonDocument } from "../office-styles.mjs";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";

const definition = () => ({ id: "body", name: "Fließtext 😀", paragraph: { textAlign: "center", spacingAfter: 12 }, character: { fontSize: 18, textColor: "blue" } });
const document = () => ({ type: "doc", attrs: { styles: [definition()] }, content: [{ type: "paragraph", attrs: { styleId: "body", textAlign: "right" }, content: [{ type: "text", text: "Café 😀 text" }] }] });

test("named styles reject malformed catalogs untrusted values and duplicate identities", () => {
  for (const value of [null, {}, [null], [{ ...definition(), name: "bad\n" }], [{ ...definition(), name: "bad\ud800" }],
    [{ ...definition(), character: { fontSize: "18" } }], [{ ...definition(), paragraph: { url: "SECRET" } }],
    [definition(), definition()], Array.from({ length: 21 }, (_, n) => ({ ...definition(), id: `style-${n}`, name: `Style ${n}` }))]) {
    expect(() => officeStyles(value)).toThrow();
  }
  expect(officeStyles([definition()])).toEqual([definition()]);
});

test("named styles resolve fixed presentation with explicit paragraph overrides", () => {
  expect(officeStyledDOMAttributes(document().content[0].attrs, officeStyles([definition()]))).toEqual({
    "data-office-font-size": "18", "data-office-text-color": "blue", "data-office-align": "right", "data-office-spacing-after": "12",
  });
  expect(() => officeStyledDOMAttributes({ styleId: "missing" }, [definition()])).toThrow();
});

test("named style definition changes are visible for bound blocks and unused catalog entries", () => {
  const before = document(), after = document();
  after.attrs.styles[0].character.fontSize = 24;
  const comparison = compareOfficeDocuments(before, after);
  expect(comparison.counts.changed).toBe(2);
  expect(describeOfficeBlock(comparison.rows[0].after).label).toContain("Schriftgröße: 24 pt");
  expect(describeOfficeBlock(comparison.rows[1].after).text).toContain("Fließtext 😀");
  delete before.content[0].attrs.styleId; delete after.content[0].attrs.styleId;
  expect(compareOfficeDocuments(before, after).counts).toEqual({ equal: 1, changed: 1, added: 0, removed: 0 });
});

test("named styles preserve source identity search positions and replacement metadata", () => {
  const before = document();
  before.content.push({ type: "paragraph", content: [{ type: "text", text: "Unbound" }] });
  const snapshot = structuredClone(before), expanded = officeStyleComparisonDocument(before);
  expect(expanded.content[1]).toBe(before.content[1]);
  expect(expanded.content[0].content).toBe(before.content[0].content);
  const result = replaceDocumentMatches(before, findDocumentMatches(before, "Café"), "New");
  expect(result.document.attrs).toEqual(before.attrs);
  expect(result.document.content[0].attrs).toEqual(before.content[0].attrs);
  expect(result.document.content[0].content[0].text).toBe("New 😀 text");
  expect(before).toEqual(snapshot);
});
