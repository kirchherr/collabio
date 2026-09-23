import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { newOfficeDraft, officeEditor, officeVersions, openOffice, saveOffice } from "./office-support.mjs";

async function expectReachableSearch(page) {
  for (const id of ["find-query", "replace-query", "find-case-sensitive", "find-whole-word", "find-next", "find-previous", "replace-current", "replace-all", "find-close"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await page.locator("#find-panel").evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const canvas = await page.locator("#page-canvas").boundingBox();
  expect(canvas).not.toBeNull();
  expect(canvas.height).toBeGreaterThan(100);
  await expect(officeEditor(page).locator(".search-match.current").first()).toBeInViewport();
}

test("Office search and replace keep the editor readable and controls reachable across viewports", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, `Synthetic responsive search ${testInfo.project.name}`, { text: "agenda overview" });
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTable");
  await page.keyboard.type("agenda owner");
  const first = await saveOffice(page);
  await page.locator("#find-toggle").click();
  await page.locator("#find-query").fill("agenda");
  await page.locator("#replace-query").fill("review");
  await page.locator("#find-whole-word").check();
  await expect(page.locator("#find-count")).toHaveText("1 / 2");
  await expectReachableSearch(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-search-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectReachableSearch(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-search-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#replace-all").click();
  await expect(officeEditor(page)).toContainText("review overview");
  await expect(officeEditor(page).locator("table")).toContainText("review owner");
  await expect(page.locator("#find-count")).toHaveText("0 Treffer");
  await page.locator("#find-close").click();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.version.previous_version_id).toBe(first.version.version_id);
  expect(JSON.stringify(saved.content)).toContain("review owner");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  verifyBrowser();
});
