import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row, column) => table(page).locator("tr").nth(row).locator("th,td").nth(column);
const matrix = (page) => table(page).locator("tr").evaluateAll((entries) => entries.map((entry) =>
  [...entry.querySelectorAll("th,td")].map((item) => item.textContent.trim())));

test("Office table rows and columns duplicate with protected headers history save reload and print", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table duplicate proof", { text: "Duplicate introduction" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await page.locator("#table-rows").fill("4"); await page.locator("#table-columns").fill("4");
  await page.locator("#table-insert-submit").click();
  const values = [
    ["Name", "Q1", "Q2", "Owner"], ["Alpha", "1", "2", "Ada"],
    ["Bravo", "3", "4", "Ben"], ["Charlie", "5", "6", "Cleo"],
  ];
  for (const [row, entries] of values.entries()) for (const [column, value] of entries.entries()) {
    await cell(page, row, column).click(); await page.keyboard.type(value);
  }
  await cell(page, 0, 1).click(); await page.locator("#table-select").selectOption("row");
  await expect(page.locator('#table-row-action option[value="duplicateRows"]')).toHaveJSProperty("disabled", true);
  await page.locator("#table-header-toggle").click();
  await cell(page, 1, 0).click(); await page.locator("#table-header-column-toggle").click();
  await cell(page, 1, 0).click(); await page.locator("#table-select").selectOption("column");
  await expect(page.locator('#table-column-action option[value="duplicateColumns"]')).toHaveJSProperty("disabled", true);
  await page.locator("#table-header-column-toggle").click();
  await cell(page, 0, 1).click(); await page.locator("#table-header-toggle").click();
  await expect(table(page).locator("tr").first().locator("th")).toHaveCount(4);

  await cell(page, 1, 1).click(); await page.locator("#table-select").selectOption("row");
  await page.locator("#table-row-action").selectOption("duplicateRows");
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Alpha", "Alpha", "Bravo", "Charlie"]);
  await page.locator('[data-command="undo"]').click();
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Alpha", "Bravo", "Charlie"]);
  await page.locator('[data-command="redo"]').click();

  await cell(page, 1, 1).click(); await page.locator("#table-select").selectOption("column");
  await page.locator("#table-column-action").selectOption("duplicateColumns");
  expect((await matrix(page))[0]).toEqual(["Name", "Q1", "Q1", "Q2", "Owner"]);
  await page.locator('[data-command="undo"]').click();
  expect((await matrix(page))[0]).toEqual(["Name", "Q1", "Q2", "Owner"]);
  await page.locator('[data-command="redo"]').click();

  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content[0].content.map((entry) => entry.type))
    .toEqual(["tableHeader", "tableHeader", "tableHeader", "tableHeader", "tableHeader"]);
  await openOfficeDocument(page, baseline.document.object_id);
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Alpha", "Alpha", "Bravo", "Charlie"]);
  expect((await matrix(page))[0]).toEqual(["Name", "Q1", "Q1", "Q2", "Owner"]);
  await page.locator("#document-print").click();
  const printed = page.locator("#print-preview table tr");
  await expect(printed).toHaveCount(5);
  expect(await printed.first().locator("th").allTextContents()).toEqual(["Name", "Q1", "Q1", "Q2", "Owner"]);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-duplicate-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
  expect(saved.version.previous_version_id).toBe(baseline.version.version_id);
});
