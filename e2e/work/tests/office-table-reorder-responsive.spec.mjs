import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row, column) => table(page).locator("tr").nth(row).locator("th,td").nth(column);
const matrix = (page) => table(page).locator("tr").evaluateAll((entries) => entries.map((entry) =>
  [...entry.querySelectorAll("th,td")].map((item) => item.textContent.trim())));

test("Office table rows and columns reorder with protected headers history save reload and print", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table reorder proof", { text: "Reorder introduction" });
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
  await expect(page.locator('#table-row-action option[value="moveRowBefore"]')).toHaveJSProperty("disabled", true);
  await expect(page.locator('#table-row-action option[value="moveRowAfter"]')).toHaveJSProperty("disabled", true);
  await page.locator("#table-header-toggle").click();
  await cell(page, 1, 0).click(); await page.locator("#table-header-column-toggle").click();
  await cell(page, 1, 0).click(); await page.locator("#table-select").selectOption("column");
  await expect(page.locator('#table-column-action option[value="moveColumnBefore"]')).toHaveJSProperty("disabled", true);
  await expect(page.locator('#table-column-action option[value="moveColumnAfter"]')).toHaveJSProperty("disabled", true);
  await page.locator("#table-header-column-toggle").click();
  await cell(page, 0, 1).click();
  await page.locator("#table-header-toggle").click();
  await expect(table(page).locator("tr").first().locator("th")).toHaveCount(4);

  await cell(page, 2, 1).click(); await page.locator("#table-select").selectOption("row");
  await page.locator("#table-row-action").selectOption("moveRowBefore");
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Bravo", "Alpha", "Charlie"]);
  await page.locator('[data-command="undo"]').click();
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Alpha", "Bravo", "Charlie"]);
  await page.locator('[data-command="redo"]').click();

  await cell(page, 1, 2).click(); await page.locator("#table-select").selectOption("column");
  await page.locator("#table-column-action").selectOption("moveColumnBefore");
  expect((await matrix(page))[0]).toEqual(["Name", "Q2", "Q1", "Owner"]);
  await page.locator('[data-command="undo"]').click();
  expect((await matrix(page))[0]).toEqual(["Name", "Q1", "Q2", "Owner"]);
  await page.locator('[data-command="redo"]').click();

  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);
  await openOfficeDocument(page, baseline.document.object_id);
  expect((await matrix(page)).map((entry) => entry[0])).toEqual(["Name", "Bravo", "Alpha", "Charlie"]);
  expect((await matrix(page))[0]).toEqual(["Name", "Q2", "Q1", "Owner"]);
  await page.locator("#document-print").click();
  const printed = page.locator("#print-preview table tr");
  expect(await printed.first().locator("th").allTextContents()).toEqual(["Name", "Q2", "Q1", "Owner"]);
  expect(await printed.evaluateAll((entries) => entries.slice(1).map((entry) => entry.querySelector("th,td").textContent.trim())))
    .toEqual(["Bravo", "Alpha", "Charlie"]);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-reorder-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
  expect(saved.version.previous_version_id).toBe(baseline.version.version_id);
});
