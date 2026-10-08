import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, TENANT_ID, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH,
  OFFICE_READER_HEADERS,
  newOfficeDraft,
  openOffice,
  saveOffice,
} from "./office-support.mjs";

test("Office document sharing is confirmed, responsive and immediately authoritative", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, `Synthetic sharing ${testInfo.project.name}`, { text: "Tenant-safe sharing proof" });
  const saved = await saveOffice(page);
  const objectId = saved.document.object_id;
  const sharePath = `${OFFICE_PATH}/${objectId}/shares`;

  const initial = page.waitForResponse((response) =>
    new URL(response.url()).pathname === sharePath && response.request().method() === "GET");
  await page.locator("#document-share").click();
  expect((await initial).status()).toBe(200);
  await expect(page.locator("#share-dialog")).toBeVisible();
  await expect(page.locator("#share-list .share-entry")).toContainText("Eigentümer · Verwaltung");
  await page.locator("#share-principal").selectOption("work-reader-e2e");
  await page.locator("#share-permission").selectOption("read");
  await expect(page.locator("#share-submit")).toBeDisabled();
  await page.locator("#share-confirm").check();

  const granted = page.waitForResponse((response) =>
    new URL(response.url()).pathname === sharePath && response.request().method() === "POST");
  await page.locator("#share-submit").click();
  const grantedResponse = await granted;
  expect(grantedResponse.status()).toBe(200);
  const grantedBody = await grantedResponse.json();
  expect(grantedBody.tenant_id).toBe(TENANT_ID);
  expect(grantedBody.acl_version).toBe(2);
  await expect(page.locator("#share-list")).toContainText("Kann lesen");

  const readerHeaders = { ...OFFICE_READER_HEADERS, "X-Readable-Object-Ids": objectId };
  let reader = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${objectId}/content`, { headers: readerHeaders });
  expect(reader.status()).toBe(200);
  expect((await reader.json()).can_write).toBe(false);

  await page.locator("#share-permission").selectOption("write");
  await page.locator("#share-confirm").check();
  const changed = page.waitForResponse((response) =>
    new URL(response.url()).pathname === sharePath && response.request().method() === "POST");
  await page.locator("#share-submit").click();
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#share-list")).toContainText("Kann bearbeiten");
  reader = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${objectId}/content`, { headers: readerHeaders });
  expect(reader.status()).toBe(200);
  expect((await reader.json()).can_write).toBe(true);

  const box = await page.locator("#share-dialog").boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-sharing-${testInfo.project.name}.png`, fullPage: true });

  page.once("dialog", (dialog) => dialog.accept());
  const revoked = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `${sharePath}/revoke` && response.request().method() === "POST");
  await page.locator("#share-list .share-entry", { hasText: "Kann bearbeiten" }).locator("button").click();
  expect((await revoked).status()).toBe(200);
  await expect(page.locator("#share-list .share-entry", { hasText: "Kann bearbeiten" })).toHaveCount(0);
  reader = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${objectId}/content`, { headers: readerHeaders });
  expect(reader.status()).toBe(404);
  verifyBrowser();
});
