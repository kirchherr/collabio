import { test, expect } from "@playwright/test";
import { officeFigureCaption, officeFigureFragment, officeFigureId, officeFigureInventory } from "../office-figures.mjs";
import { officeReferenceInventory, officeCrossReferenceDescription } from "../office-bookmarks.mjs";

const firstId = "figure-111111111111111111111111";
const secondId = "figure-222222222222222222222222";
const document = (order = [firstId, secondId]) => ({ type: "doc", content: order.map((id) => ({
  type: "image", attrs: { figureId: id, caption: id === firstId ? "Overview" : "Details" },
})) });

test("Office figure model derives numbers from order while keeping stable identities", () => {
  expect(officeFigureId(firstId)).toBe(firstId);
  expect(officeFigureFragment(firstId)).toBe(`office-figure-${firstId}`);
  expect(officeFigureInventory(document()).map(({ id, number, label }) => ({ id, number, label }))).toEqual([
    { id: firstId, number: 1, label: "Abbildung 1: Overview" },
    { id: secondId, number: 2, label: "Abbildung 2: Details" },
  ]);
  expect(officeFigureInventory(document([secondId, firstId])).map(({ id, number }) => ({ id, number }))).toEqual([
    { id: secondId, number: 1 }, { id: firstId, number: 2 },
  ]);
  expect(officeFigureCaption({ figureId: firstId, caption: "Overview" }, 2)).toBe("Abbildung 2: Overview");
  expect(officeFigureCaption({ caption: "Legacy caption" })).toBe("Legacy caption");
});

test("Office reference inventory combines bookmarks and figures without ambiguous targets", () => {
  const value = document();
  value.content.push({ type: "paragraph", content: [
    { type: "bookmark", attrs: { id: "bookmark-summary", label: "Summary" } },
  ] });
  const targets = officeReferenceInventory(value);
  expect(targets.map(({ id }) => id)).toEqual(["bookmark-summary", firstId, secondId]);
  expect(officeCrossReferenceDescription({ targetId: secondId }, targets)).toBe("Querverweis: Abbildung 2: Details");
  value.content.at(-1).content[0].attrs.id = firstId;
  expect(() => officeReferenceInventory(value)).toThrow();
});
