import { test, expect } from "@playwright/test";
import { officeReferenceInventory, officeCrossReferenceDescription } from "../office-bookmarks.mjs";
import { officeTableAttributes, officeTableCaption, officeTableFragment, officeTableId, officeTableInventory } from "../office-tables.mjs";

const firstId = "table-111111111111111111111111";
const secondId = "table-222222222222222222222222";
const row = { type: "tableRow", content: [{ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [{ type: "paragraph" }] }] };
const table = (id, caption) => ({ type: "table", attrs: { tableId: id, caption }, content: [row] });
const document = (order = [table(firstId, "Overview"), table(secondId, "Details")]) => ({ type: "doc", content: order });

test("Office table captions use their own order-derived sequence and stable identities", () => {
  expect(officeTableId(firstId)).toBe(firstId);
  expect(officeTableFragment(firstId)).toBe(`office-table-${firstId}`);
  expect(officeTableAttributes({ caption: "Overview", tableId: firstId })).toEqual({ caption: "Overview", tableId: firstId });
  expect(officeTableCaption({ caption: "Overview", tableId: firstId }, 2)).toBe("Tabelle 2: Overview");
  expect(officeTableInventory(document()).map(({ id, number, label }) => ({ id, number, label }))).toEqual([
    { id: firstId, number: 1, label: "Tabelle 1: Overview" },
    { id: secondId, number: 2, label: "Tabelle 2: Details" },
  ]);
  expect(officeTableInventory(document([table(secondId, "Details"), table(firstId, "Overview")])).map(({ id, number }) => ({ id, number })))
    .toEqual([{ id: secondId, number: 1 }, { id: firstId, number: 2 }]);
});

test("Office reference inventory keeps table and figure sequences separate and rejects collisions", () => {
  const value = document();
  value.content.unshift({ type: "image", attrs: { figureId: "figure-aaaaaaaaaaaaaaaaaaaaaaaa", caption: "Chart" } });
  const targets = officeReferenceInventory(value);
  expect(targets.map(({ kind, number }) => ({ kind, number }))).toEqual([
    { kind: "figure", number: 1 }, { kind: "table", number: 1 }, { kind: "table", number: 2 },
  ]);
  expect(officeCrossReferenceDescription({ targetId: secondId }, targets)).toBe("Querverweis: Tabelle 2: Details");
  value.content[1].attrs.tableId = "figure-aaaaaaaaaaaaaaaaaaaaaaaa";
  expect(() => officeReferenceInventory(value)).toThrow();
});
