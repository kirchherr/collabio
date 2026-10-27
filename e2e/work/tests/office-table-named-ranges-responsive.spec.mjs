import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office names a range and calculates it from another table with deterministic dates", async ({ page }, testInfo) => {
  test.setTimeout(75_000); await openOffice(page);
  await newOfficeDraft(page, "Named range proof", { text: "Cross-table calculation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Item\tPrice\nAlpha\t7");
  const tables = officeEditor(page).locator("table");
  await tables.nth(0).locator("tr").nth(1).locator("td").nth(1).click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Prices");
  await page.locator("#table-caption-apply").click();
  await tables.nth(0).locator("tr").nth(1).locator("td").nth(1).click();
  await expect(page.locator("#table-range")).toBeEnabled(); await page.locator("#table-range").click();
  await expect(page.locator("#table-range-summary")).toContainText("B2:B2");
  await page.locator("#table-range-name").fill("UNIT_PRICE"); await page.locator("#table-range-apply").click();

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Result\t0");
  const result = tables.nth(1).locator("tr").first().locator("td").nth(1); await result.click();
  await page.locator("#table-formula").click();
  await page.locator("#table-formula-source").fill("=UNIT_PRICE*2+YEAR(DATUM(2026;10;12))");
  await page.locator("#table-formula-apply").click(); await expect(result).toHaveText("2040");

  const saved = await saveOffice(page);
  expect(saved.content.attrs.tableRanges).toEqual([{ name: "UNIT_PRICE", tableId: expect.stringMatching(/^table-/), range: "B2:B2" }]);
  expect(saved.content.content.filter((entry) => entry.type === "table")[1].content[0].content[1].attrs)
    .toMatchObject({ formula: "=UNIT_PRICE*2+YEAR(DATE(2026,10,12))", formulaResult: "2040" });
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator("table").nth(1).locator("td").nth(1)).toHaveText("2040");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-named-range-${testInfo.project.name}.png`, fullPage: true });
});
