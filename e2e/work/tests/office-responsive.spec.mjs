import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office native editor, confirmation and persisted document fit the viewport", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, `Synthetic responsive Office ${testInfo.project.name}`, { template: "meeting" });
  await expect(officeEditor(page).locator("h1")).toHaveText("Besprechungsnotiz");
  await officeEditor(page).press("Control+End");
  await page.keyboard.type("Responsive editing result");
  await page.locator("#document-save").click();
  const dialog = await page.locator("#save-dialog").boundingBox();
  expect(dialog).not.toBeNull();
  expect(dialog.x).toBeGreaterThanOrEqual(0);
  expect(dialog.x + dialog.width).toBeLessThanOrEqual(page.viewportSize().width);
  await expect(page.locator("#save-confirm")).toBeInViewport();
  await expect(page.locator("#save-submit")).toBeInViewport();
  await page.locator('#save-dialog [data-close-dialog]').first().click();
  const saved = await saveOffice(page);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page)).toContainText("Responsive editing result");
  await expect(page.locator("#document-close")).toBeInViewport();
  await expect(page.locator("#document-save")).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-editor-${testInfo.project.name}.png`, fullPage: true });
  verifyBrowser();
});
