import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const row = (page, index) => table(page).locator("tr").nth(index);
const cell = (page, rowIndex, columnIndex = 0) => row(page, rowIndex).locator("th,td").nth(columnIndex);

async function styleSelection(page, fill, vertical) {
  await page.locator("#table-cell-style").click();
  await expect(page.locator("#table-cell-style-dialog")).toBeVisible();
  await page.locator("#table-cell-fill").selectOption(fill);
  await page.locator("#table-cell-vertical").selectOption(vertical);
  await page.locator("#table-cell-style-apply").click();
  await expect(page.locator("#table-cell-style-dialog")).toBeHidden();
}

test("Office table cell fills and vertical alignment preserve selection history save reload and print", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table cell style proof", { text: "Cell style introduction" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await page.locator("#table-rows").fill("3"); await page.locator("#table-columns").fill("3");
  await page.locator("#table-with-header").uncheck(); await page.locator("#table-insert-submit").click();
  for (const [r, c, text] of [[0, 0, "Quarter"], [0, 1, "Plan"], [0, 2, "Actual"], [1, 0, "Q1"], [1, 1, "120"], [1, 2, "110"]]) {
    await cell(page, r, c).click(); await page.keyboard.type(text);
  }

  await cell(page, 0).click(); await page.locator("#table-select").selectOption("row");
  await styleSelection(page, "blue", "middle");
  await expect(row(page, 0).locator("td[data-office-cell-fill=blue][data-office-cell-vertical=middle]")).toHaveCount(3);
  await page.locator('[data-command="undo"]').click();
  await expect(row(page, 0).locator("td[data-office-cell-fill]")).toHaveCount(0);
  await page.locator('[data-command="redo"]').click();
  await expect(row(page, 0).locator("td[data-office-cell-fill=blue]")).toHaveCount(3);
  await page.locator("#table-merge").click();
  await expect(cell(page, 0)).toHaveAttribute("colspan", "3");
  await expect(cell(page, 0)).toHaveAttribute("data-office-cell-fill", "blue");

  await cell(page, 1).click(); await styleSelection(page, "yellow", "bottom");
  await expect(cell(page, 1)).toHaveAttribute("data-office-cell-fill", "yellow");
  await expect(cell(page, 1)).toHaveAttribute("data-office-cell-vertical", "bottom");
  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content[0].content[0].attrs).toMatchObject({ colspan: 3, rowspan: 1, background: "blue", verticalAlign: "middle" });
  expect(savedTable.content[1].content[0].attrs).toMatchObject({ background: "yellow", verticalAlign: "bottom" });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);

  await openOfficeDocument(page, baseline.document.object_id);
  await expect(cell(page, 0)).toHaveAttribute("data-office-cell-fill", "blue");
  await expect(cell(page, 1)).toHaveAttribute("data-office-cell-vertical", "bottom");
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview td[data-office-cell-fill=blue]")).toHaveCount(1);
  await expect(page.locator("#print-preview td[data-office-cell-fill=yellow]")).toHaveCount(1);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-cell-style-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
