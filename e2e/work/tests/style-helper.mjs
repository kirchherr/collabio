import { expect } from "@playwright/test";
import { officeEditor, openOffice, openOfficeDocument } from "./office-support.mjs";
import { createParagraphFixture, paragraph } from "./paragraph-helper.mjs";

export const styleDefinition = () => ({ id: "body", name: "Fließtext", paragraph: { textAlign: "center", lineSpacing: "1.5", spacingAfter: 12 }, character: { fontSize: 18, textColor: "blue" } });
export function styleDocument({ linked = true } = {}) {
  const attrs = linked ? { styleId: "body" } : {};
  const cell = (text) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text, attrs)] });
  return { type: "doc", ...(linked ? { attrs: { styles: [styleDefinition()] } } : {}), content: [
    { type: "heading", attrs: { level: 2, ...attrs }, content: [{ type: "text", text: "Style heading Café 😀" }] },
    paragraph("First paragraph", attrs, ["bold"]), paragraph("Second paragraph", attrs),
    { type: "bulletList", content: [{ type: "listItem", content: [paragraph("List item", attrs)] }] },
    { type: "table", content: [{ type: "tableRow", content: [cell("First cell"), cell("Second cell")] }] },
    { type: "codeBlock", content: [{ type: "text", text: "Code stays unchanged" }] },
  ] };
}
export async function styleFixture(page, document = styleDocument()) {
  const first = await createParagraphFixture(page, "Synthetic named styles", document);
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  return first;
}
export async function openStyles(page) {
  await page.locator("#style-options").click();
  await expect(page.locator("#style-dialog")).toBeVisible();
}
export async function styleValues(page, choices) {
  for (const [key, value] of Object.entries(choices)) {
    if (key === "name") await page.locator("#style-name").fill(value);
    else await page.locator(`#style-${key}`).selectOption(String(value));
  }
}
export async function applyStyle(page, { choice = null, values = {}, update = false } = {}) {
  await openStyles(page);
  if (choice) await page.locator("#style-choice").selectOption(choice);
  await styleValues(page, values);
  await page.locator(update ? "#style-update" : "#style-apply").click();
  await expect(page.locator("#style-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
}
