import path from "node:path";

import { test, expect } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { closeCrm, openCrm, readCrm } from "./crm-support.mjs";

test("CRM account details, contact data and activities fit the viewport with an accessible close action", async ({ page }, testInfo) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openCrm(page);
  await readCrm(page);
  const layout = await page.locator("#crm-detail-dialog").evaluate((dialog) => {
    const bounds = dialog.getBoundingClientRect();
    const content = document.querySelector("#crm-detail-content");
    return {
      left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom,
      clientWidth: dialog.clientWidth, scrollWidth: dialog.scrollWidth,
      contentWidth: content.clientWidth, contentScrollWidth: content.scrollWidth,
      viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
    };
  });
  expect(layout.left).toBeGreaterThanOrEqual(0);
  expect(layout.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
  expect(layout.top).toBeGreaterThanOrEqual(0);
  expect(layout.bottom).toBeLessThanOrEqual(layout.viewportHeight + 1);
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(layout.contentScrollWidth).toBeLessThanOrEqual(layout.contentWidth + 1);
  await page.locator("#crm-detail-content").evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect(page.getByTestId("crm-detail-activity").last()).toBeInViewport();
  await page.locator("#crm-detail-close").scrollIntoViewIfNeeded();
  await expect(page.locator("#crm-detail-close")).toBeInViewport();
  await page.screenshot({ path: path.join(ARTIFACT_DIR, `work-crm-detail-${testInfo.project.name}.png`), fullPage: true });
  await closeCrm(page);
  assertClean();
});
