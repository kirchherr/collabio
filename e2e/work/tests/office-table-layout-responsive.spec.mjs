import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row, column = 0) => table(page).locator("tr").nth(row).locator("th,td").nth(column);

test("Office table layout presets preserve one-step history save reload comparison and print", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  await newOfficeDraft(page, "Native table layout proof", { text: "Layout introduction" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await page.locator("#table-rows").fill("3"); await page.locator("#table-columns").fill("3");
  await page.locator("#table-insert-submit").click();
  for (const [r, c, text] of [[0, 0, "Quarter"], [0, 1, "Plan"], [0, 2, "Actual"], [1, 0, "Q1"], [1, 1, "120"], [1, 2, "110"]]) {
    await cell(page, r, c).click(); await page.keyboard.type(text);
  }
  await cell(page, 0).click(); await page.locator("#table-caption").click();
  await page.locator("#table-caption-text").fill("Quarterly performance");
  await page.locator("#table-caption-apply").click();

  await page.locator("#table-layout").click();
  await expect(page.locator("#table-layout-dialog")).toBeVisible();
  await page.locator("#table-layout-style").selectOption("accent");
  await page.locator("#table-layout-width").selectOption("compact");
  await page.locator("#table-layout-align").selectOption("center");
  await page.locator("#table-layout-columns").selectOption("first-wide");
  await page.locator("#table-layout-caption").selectOption("top");
  await page.locator("#table-layout-apply").click();
  await expect(table(page)).toHaveAttribute("data-office-table-style", "accent");
  await expect(table(page)).toHaveAttribute("data-office-table-width", "compact");
  await expect(table(page)).toHaveAttribute("data-office-table-align", "center");
  await expect(table(page)).toHaveAttribute("data-office-table-columns", "first-wide");
  await expect(table(page)).toHaveAttribute("data-office-caption-position", "top");

  await page.locator('[data-command="undo"]').click();
  await expect(table(page)).not.toHaveAttribute("data-office-table-style");
  await page.locator('[data-command="redo"]').click();
  await expect(table(page)).toHaveAttribute("data-office-table-style", "accent");
  await page.locator("#table-layout").click(); await page.locator("#table-layout-reset").click();
  await expect(table(page)).not.toHaveAttribute("data-office-table-width");
  await page.locator('[data-command="undo"]').click();
  await expect(table(page)).toHaveAttribute("data-office-table-width", "compact");

  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.attrs).toMatchObject({ style: "accent", width: "compact", align: "center",
    columns: "first-wide", captionPosition: "top", caption: "Quarterly performance" });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);

  await openOfficeDocument(page, baseline.document.object_id);
  await expect(table(page)).toHaveAttribute("data-office-table-style", "accent");
  await page.locator("#document-print").click();
  const printed = page.locator("#print-preview table").first();
  await expect(printed).toHaveAttribute("data-office-table-width", "compact");
  await expect(printed).toHaveAttribute("data-office-caption-position", "top");
  await expect(printed.locator("caption")).toContainText("Quarterly performance");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-layout-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
