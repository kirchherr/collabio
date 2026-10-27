import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row, column) => table(page).locator("tr").nth(row).locator("th,td").nth(column);
const rows = (page) => table(page).locator("tr").evaluateAll((entries) => entries.map((entry) =>
  [...entry.querySelectorAll("th,td")].map((item) => item.textContent.trim())));

async function sort(page, column, type, direction) {
  await page.locator("#table-sort").click();
  await expect(page.locator("#table-sort-dialog")).toBeVisible();
  await page.locator("#table-sort-column").selectOption(String(column));
  await page.locator("#table-sort-type").selectOption(type);
  await page.locator("#table-sort-direction").selectOption(direction);
  await page.locator("#table-sort-apply").click();
}

test("Office table sorting preserves stable rows history save reload and print", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table sorting proof", { text: "Sorting introduction" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await page.locator("#table-rows").fill("4"); await page.locator("#table-columns").fill("3");
  await page.locator("#table-insert-submit").click();
  const values = [
    ["Name", "Amount", "Date"], ["Charlie", "2", "2026-02-01"],
    ["Alpha", "10", "2025-12-31"], ["Bravo", "2", "2026-01-15"],
  ];
  for (const [row, entries] of values.entries()) for (const [column, value] of entries.entries()) {
    await cell(page, row, column).click(); await page.keyboard.type(value);
  }

  await cell(page, 1, 0).click(); await sort(page, 0, "number", "ascending");
  await expect(page.locator("#table-sort-status")).toContainText("Datentyp passen");
  await page.locator("#table-sort-cancel").click();
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Charlie", "Alpha", "Bravo"]);

  await sort(page, 1, "number", "descending");
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Alpha", "Charlie", "Bravo"]);
  await page.locator('[data-command="undo"]').click();
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Charlie", "Alpha", "Bravo"]);
  await sort(page, 2, "date", "ascending");
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Alpha", "Bravo", "Charlie"]);
  await page.locator('[data-command="undo"]').click();
  await sort(page, 0, "text", "ascending");
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Alpha", "Bravo", "Charlie"]);
  await page.locator('[data-command="undo"]').click(); await page.locator('[data-command="redo"]').click();
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Alpha", "Bravo", "Charlie"]);

  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content.slice(1).map((entry) => entry.content[0].content[0].content[0].text))
    .toEqual(["Alpha", "Bravo", "Charlie"]);

  await openOfficeDocument(page, baseline.document.object_id);
  expect((await rows(page)).slice(1).map((entry) => entry[0])).toEqual(["Alpha", "Bravo", "Charlie"]);
  await page.locator("#document-print").click();
  const printed = page.locator("#print-preview table tr");
  await expect(printed).toHaveCount(4);
  expect(await printed.evaluateAll((entries) => entries.slice(1).map((entry) => entry.querySelector("td,th").textContent.trim())))
    .toEqual(["Alpha", "Bravo", "Charlie"]);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-sort-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
