import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const row = (page, index) => table(page).locator("tr").nth(index);
const cell = (page, rowIndex, columnIndex = 0) => row(page, rowIndex).locator("th,td").nth(columnIndex);

test("Office merged cells split header columns save reload and print responsively", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table span proof", { text: "Table span introduction" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await page.locator("#table-rows").fill("3"); await page.locator("#table-columns").fill("3");
  await page.locator("#table-with-header").uncheck(); await page.locator("#table-insert-submit").click();
  for (const [r, c, text] of [[0, 0, "Quarter"], [0, 1, "Plan"], [0, 2, "Actual"], [1, 0, "Q1"], [1, 1, "120"], [1, 2, "110"]]) {
    await cell(page, r, c).click(); await page.keyboard.type(text);
  }
  await cell(page, 0).click(); await page.locator("#table-select").selectOption("row");
  await expect(page.locator("#table-merge")).toBeEnabled(); await page.locator("#table-merge").click();
  await expect(page.locator("#table-sort")).toBeDisabled();
  await expect(page.locator('#table-row-action option[value="moveRowBefore"]')).toBeDisabled();
  await expect(page.locator('#table-column-action option[value="moveColumnAfter"]')).toBeDisabled();
  await expect(row(page, 0).locator("th,td")).toHaveCount(1);
  await expect(cell(page, 0)).toHaveAttribute("colspan", "3");
  await page.locator('[data-command="undo"]').click(); await expect(row(page, 0).locator("td")).toHaveCount(3);
  await page.locator('[data-command="redo"]').click(); await expect(cell(page, 0)).toHaveAttribute("colspan", "3");
  await expect(page.locator("#table-split")).toBeEnabled(); await page.locator("#table-split").click();
  await expect(row(page, 0).locator("td")).toHaveCount(3);
  await page.locator('[data-command="undo"]').click(); await expect(cell(page, 0)).toHaveAttribute("colspan", "3");
  await cell(page, 1).click(); await page.locator("#table-header-column-toggle").click();
  await expect(page.locator("#table-header-column-toggle")).toHaveAttribute("aria-pressed", "true");
  await expect(table(page).locator("tr > th:first-child")).toHaveCount(3);
  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content[0].content[0]).toMatchObject({ type: "tableHeader", attrs: { colspan: 3, rowspan: 1 } });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);
  await openOfficeDocument(page, baseline.document.object_id);
  await expect(cell(page, 0)).toHaveAttribute("colspan", "3");
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview table tr").first().locator("th")).toHaveAttribute("colspan", "3");
  await expect(page.locator("#print-preview table tbody tr").first().locator("th")).toHaveAttribute("scope", "row");
  expect(await page.locator("#print-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-spans-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
