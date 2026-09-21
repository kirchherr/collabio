import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, installContext } from "./support.mjs";
import { officeEditor, openOfficeDocument, showDocumentList } from "./office-support.mjs";
import {
  DISCOVERY_EDITOR_ID, appendDiscovery, discoveryCards, discoveryResponse,
  matchesDiscoveryPage, searchDiscovery,
} from "./office-discovery-support.mjs";

async function expectDiscoveryLayout(page) {
  await showDocumentList(page);
  for (const id of ["documents-search", "documents-refresh", "documents-load-more", "documents-status"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  await discoveryCards(page).nth(50).scrollIntoViewIfNeeded();
  await expect(discoveryCards(page).nth(50)).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator("#documents-list").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
}

test("Office discovery remains reachable from Work with search and pagination on desktop tablet and mobile", async ({ page }, testInfo) => {
  await installContext(page, { userId: DISCOVERY_EDITOR_ID, roleIds: "office-editor" });
  await page.goto(`${BASE_URL}/work`);
  const opened = page.waitForResponse((response) => matchesDiscoveryPage(response, ""));
  await page.locator('a[href="/office"]').click();
  const first = await discoveryResponse(await opened);
  await expect(page).toHaveURL(`${BASE_URL}/office`);
  await expect(discoveryCards(page)).toHaveCount(50);
  await openOfficeDocument(page, first.documents[0].object_id);
  await expect(officeEditor(page)).toContainText("Synthetic discovery document");
  const filtered = await searchDiscovery(page, "Discovery");
  const appended = await appendDiscovery(page, filtered, 50);
  await expect(page.locator(`[data-document-id="${appended.documents[0].object_id}"]`)).toBeFocused();
  await expectDiscoveryLayout(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-discovery-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectDiscoveryLayout(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-discovery-tablet-chromium.png`, fullPage: true });
  }
  const exact = await searchDiscovery(page, "Discovery 000");
  await openOfficeDocument(page, exact.documents[0].object_id);
  await expect(officeEditor(page)).toHaveText("Synthetic discovery document 000.");
  await expect(officeEditor(page)).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
