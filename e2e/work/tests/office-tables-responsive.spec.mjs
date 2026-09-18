import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { newOfficeDraft, officeEditor, officeVersions, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function expectReachableTableTools(page) {
  for (const id of ["table-info", "table-row-action", "table-column-action", "table-select", "table-header-toggle", "table-delete"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await page.locator("#table-tools").evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(officeEditor(page).locator(".selectedCell").first()).toBeInViewport();
  const canvas = await page.locator("#page-canvas").boundingBox();
  expect(canvas).not.toBeNull();
  expect(canvas.height).toBeGreaterThan(100);
}

test("Office configurable table dialog, selected cells and contextual actions fit desktop, tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, `Synthetic responsive tables ${testInfo.project.name}`, { text: "Responsibilities and next steps" });
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await expect(page.locator("#table-insert-dialog")).toBeVisible();
  for (const id of ["table-rows", "table-columns", "table-with-header", "table-insert-submit", "table-insert-cancel"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  await page.locator("#table-rows").fill("3");
  await page.locator("#table-columns").fill("3");
  await page.locator("#table-with-header").check();
  await page.locator("#table-insert-submit").click();
  await expect(page.locator("#table-insert-dialog")).toBeHidden();
  await page.keyboard.type("Owner");
  const table = officeEditor(page).locator("table");
  await table.locator("tr").nth(1).locator("td").first().click();
  await page.keyboard.type("Project team");
  await page.locator("#table-select").selectOption("row");
  await expect(table.locator(".selectedCell")).toHaveCount(3);
  await expectReachableTableTools(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-tables-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectReachableTableTools(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-tables-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#table-delete").click();
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  await expect(page.locator("#table-remove-confirm")).toBeInViewport();
  await expect(page.locator("#table-remove-cancel")).toBeInViewport();
  await page.locator("#table-remove-cancel").click();
  await expect(table).toContainText("Project team");
  const saved = await saveOffice(page);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator("table tr")).toHaveCount(3);
  await expect(officeEditor(page).locator("table")).toContainText("Owner");
  await expect(officeEditor(page).locator("table")).toContainText("Project team");
  expect(await officeVersions(page, saved.document.object_id)).toHaveLength(1);
  verifyBrowser();
});
