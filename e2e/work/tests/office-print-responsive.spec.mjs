import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, officeVersions, openOffice } from "./office-support.mjs";
import { expectPrintCleared, installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

async function expectPrintLayout(page) {
  const dialog = page.locator("#print-dialog");
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  for (const id of ["print-paper", "print-orientation", "print-submit", "print-close"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  await expect(page.locator("#print-preview")).toContainText("Responsive saved print source");
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("Office print preview settings and explicit printing fit desktop tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const first = await createOfficeDocument(page, `Synthetic print ${testInfo.project.name}`, "Responsive saved print source: decisions remain readable on every screen.");
  const objectId = first.document.object_id;
  const versionId = first.version.version_id;
  const calls = await installPrintProbe(page);
  await openPrintPreview(page, objectId, versionId);
  await expect(page.locator("#print-paper")).toHaveValue("a4");
  await expect(page.locator("#print-orientation")).toHaveValue("portrait");
  await expectPrintLayout(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-print-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-paper").selectOption("letter");
  await page.locator("#print-orientation").selectOption("landscape");
  await expectPrintLayout(page);
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectPrintLayout(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-print-tablet-chromium.png`, fullPage: true });
  }
  await submitOfficePrint(page, objectId, versionId);
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].snapshot.className).toContain("paper-letter");
  expect(calls[0].snapshot.className).toContain("orientation-landscape");
  await expectPrintCleared(page);
  if (await page.locator("#print-dialog").isVisible()) await page.locator("#print-close").click();
  await expect(officeEditor(page)).toBeInViewport();
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  verifyBrowser();
});
