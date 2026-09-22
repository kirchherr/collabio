import { expect, test } from "@playwright/test";

import { createParagraphFixture, richParagraphDocument } from "./paragraph-helper.mjs";
import { officeEditor, openOffice, openOfficeDocument } from "./office-support.mjs";

test("Office keyboard replaces a whole rich document ending in a table", async ({ page }) => {
  const document = richParagraphDocument();
  document.content.pop();
  const saved = await createParagraphFixture(page, "Synthetic whole-document keyboard", document);
  await openOffice(page);
  await openOfficeDocument(page, saved.document.object_id);
  await officeEditor(page).press("Control+a");
  console.log("selection-debug", await officeEditor(page).evaluate((element) => {
    const editor = element.parentElement.editor || element.editor;
    const selection = editor?.state.selection;
    return { elementKeys: Object.keys(element), parentKeys: Object.keys(element.parentElement), selection: selection?.toJSON(), type: selection?.constructor.name };
  }));
  await page.keyboard.insertText("Whole document replacement");
  console.log("after-input", await officeEditor(page).evaluate((element) => ({ html: element.innerHTML, notice: document.querySelector("#document-notice").textContent })));
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  await page.locator("#table-remove-confirm").click();
  await expect(officeEditor(page)).toHaveText("Whole document replacement");
});
