import { expect } from "@playwright/test";
import { createParagraphFixture, paragraph, richParagraphDocument } from "./paragraph-helper.mjs";
import { officeEditor, openOffice, openOfficeDocument } from "./office-support.mjs";
import { selectCharacters } from "./character-helper.mjs";

export const SAMPLE_PARAGRAPH = { textAlign: "center", lineSpacing: "1.5", spacingBefore: 6, spacingAfter: 12 };
export const SAMPLE_MARKS = [{ type: "bold" }, { type: "underline" }, { type: "textStyle", attrs: { fontSize: 24, textColor: "purple" } }];
export function transferDocument() {
  const doc = richParagraphDocument();
  doc.content.unshift({ type: "paragraph", attrs: SAMPLE_PARAGRAPH, content: [{ type: "text", text: "Format source", marks: SAMPLE_MARKS }] });
  doc.content.push(paragraph("Plain destination Café 😀 END"));
  return doc;
}
export async function transferFixture(page, document = transferDocument()) {
  const saved = await createParagraphFixture(page, "Synthetic format transfer", document);
  await openOffice(page); await openOfficeDocument(page, saved.document.object_id);
  return saved;
}
export async function transfer(page, action) {
  await page.locator("#format-transfer").selectOption(action);
  await expect(officeEditor(page)).toBeFocused();
}
export async function captureSample(page) {
  await selectCharacters(page, 0, 2);
  await transfer(page, "copy");
  await expect(page.locator("#format-sample")).toContainText("24 pt");
}
