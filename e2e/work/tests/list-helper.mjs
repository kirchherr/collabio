import { expect } from "@playwright/test";
import { createParagraphFixture, paragraph } from "./paragraph-helper.mjs";
import { officeEditor, openOffice, openOfficeDocument } from "./office-support.mjs";

export const listItem = (...content) => ({ type: "listItem", content });
export const ordered = (start, ...content) => ({ type: "orderedList", attrs: { start }, content });
export function listDocument() {
  const styled = paragraph("Café 😀 second", { textAlign: "right", spacingAfter: 12 });
  styled.content[0].marks = [{ type: "textStyle", attrs: { fontSize: 18, textColor: "green" } }];
  const cell = (...content) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content });
  return { type: "doc", content: [
    paragraph("Outside"),
    ordered(7, listItem(paragraph("First parent", { textAlign: "center" }, ["bold"])), listItem(styled),
      listItem(paragraph("Third item", {}, ["italic"])), listItem(paragraph("Last sibling"))),
    { type: "bulletList", content: [listItem(paragraph("Bullet parent"),
      ordered(20, listItem(paragraph("Nested first")), listItem(paragraph("Nested second"))))] },
    { type: "table", content: [{ type: "tableRow", content: [
      cell(ordered(3, listItem(paragraph("Cell first")), listItem(paragraph("Cell second")))), cell(paragraph("Other cell")),
    ] }] },
    { type: "codeBlock", content: [{ type: "text", text: "Code stays code" }] }, paragraph("After"),
  ] };
}
export async function listFixture(page, document = listDocument()) {
  const saved = await createParagraphFixture(page, "Synthetic list editing", document);
  await openOffice(page); await openOfficeDocument(page, saved.document.object_id);
  return saved;
}
export async function openListOptions(page) {
  await expect(page.locator("#list-options")).toBeEnabled();
  await page.locator("#list-options").click();
  await expect(page.locator("#list-dialog")).toBeVisible();
}
export async function listLevel(page, direction) {
  await openListOptions(page);
  await page.locator(`#list-${direction}`).click();
  await expect(page.locator("#list-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
}
export async function listStart(page, value) {
  await openListOptions(page);
  await page.locator("#list-start").fill(String(value));
  await page.locator("#list-apply").click();
}
