import { expect, test } from "@playwright/test";

import {
  officeBibliographyLabel, officeCitationAttributes, officeCitationLabel, officeCitationSources,
  officeDocumentFields, officeEquationAttributes, officeFieldAttributes, officeNoteAttributes,
  officeOpaqueId, officeSemanticInventory,
} from "../office-semantics.mjs";
import { officeResolveRunningFields } from "../office-running.mjs";

const field = { key: "project", label: "Project", value: "Apollo" };
const source = { id: "source-111111111111111111111111", author: "Ada Lovelace", title: "Notes", year: "1843", locator: "Archive" };

test("Office semantic catalogs, numbering and derived views remain deterministic", () => {
  expect(officeDocumentFields([field])).toEqual([field]);
  expect(officeCitationSources([source])).toEqual([source]);
  expect(officeFieldAttributes({ key: "project" }, [field]).value).toBe("Apollo");
  expect(officeFieldAttributes({ key: "missing" }, [field]).value).toContain("Fehlendes Feld");
  expect(officeNoteAttributes({ id: "note-222222222222222222222222", kind: "footnote", text: "Proof" }).text).toBe("Proof");
  expect(officeCitationAttributes({ sourceId: source.id, locator: "p. 12" }, [source]).source).toEqual(source);
  expect(officeCitationLabel(source, "p. 12")).toBe("[Ada Lovelace, 1843, p. 12]");
  expect(officeBibliographyLabel(source)).toBe("Ada Lovelace. 1843. Notes. Archive");
  expect(officeResolveRunningFields({ header: "{{field:project}}", footer: "", numbering: "none" }, [field]).header).toBe("Apollo");
  expect(officeResolveRunningFields({ header: "{{field:missing}}", footer: "", numbering: "none" }, [field]).header).toContain("Fehlendes Feld");
  expect(officeEquationAttributes({ id: "equation-333333333333333333333333", source: "x = 1", alt: "x equals one" }).source).toBe("x = 1");

  const document = { type: "doc", attrs: { documentFields: [field], citationSources: [source] }, content: [
    { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Overview" }] },
    { type: "paragraph", content: [
      { type: "documentField", attrs: { key: "project" } },
      { type: "noteReference", attrs: { id: "note-222222222222222222222222", kind: "footnote", text: "Proof" } },
      { type: "citationReference", attrs: { sourceId: source.id, locator: "p. 12" } },
    ] },
    { type: "equation", attrs: { id: "equation-333333333333333333333333", source: "x = 1", alt: "x equals one" } },
  ] };
  const inventory = officeSemanticInventory(document);
  expect(inventory.headings).toEqual([{ level: 1, text: "Overview" }]);
  expect(inventory.notes.map(({ kind, number }) => ({ kind, number }))).toEqual([{ kind: "footnote", number: 1 }]);
  expect(inventory.equations[0].number).toBe(1);
  expect(inventory.references.map(({ kind }) => kind)).toEqual(["field", "footnote", "citation", "equation"]);
});

test("Office semantic validators reject ambiguous catalogs and generate bounded opaque IDs", () => {
  expect(() => officeDocumentFields([field, field])).toThrow();
  expect(() => officeCitationSources([source, source])).toThrow();
  const cryptoObject = { getRandomValues(bytes) { bytes.fill(0xab); return bytes; } };
  expect(officeOpaqueId("note", cryptoObject)).toBe("note-abababababababababababab");
});
