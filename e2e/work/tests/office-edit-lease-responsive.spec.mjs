import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import {
  createOfficeDocument,
  officeEditor,
  openOffice,
  openOfficeDocument,
} from "./office-support.mjs";

test("Office edit lease protects drafts across two browser sessions and requires confirmed takeover", async ({ browser, page }, testInfo) => {
  test.setTimeout(60000);
  const verifyFirst = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const saved = await createOfficeDocument(page, `Synthetic edit lease ${testInfo.project.name}`, "Authoritative saved text");
  const objectId = saved.document.object_id;
  await expect(page.locator("#edit-lease-banner")).toContainText("Bearbeitung für diese Sitzung reserviert");
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await officeEditor(page).fill("Unsaved first-session draft");

  const secondContext = await browser.newContext();
  const secondPage = await secondContext.newPage();
  const verifySecond = monitorPage(secondPage, { baseUrls: [BASE_URL] });
  try {
    await openOffice(secondPage, { readableObjectIds: objectId });
    await openOfficeDocument(secondPage, objectId);
    await expect(secondPage.locator("#edit-lease-banner")).toContainText("Eine andere Sitzung bearbeitet diese Version");
    await expect(officeEditor(secondPage)).toHaveAttribute("contenteditable", "false");
    await expect(secondPage.locator("#edit-lease-takeover")).toBeVisible();

    await secondPage.locator("#edit-lease-takeover").click();
    await expect(secondPage.locator("#edit-lease-dialog")).toBeVisible();
    await expect(secondPage.locator("#edit-lease-submit")).toBeDisabled();
    await secondPage.locator("#edit-lease-confirm").check();
    const takeover = secondPage.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/v1/office/documents/${objectId}/edit-lease` && response.request().method() === "POST";
    });
    await secondPage.locator("#edit-lease-submit").click();
    expect((await takeover).status()).toBe(200);
    await expect(secondPage.locator("#edit-lease-dialog")).toBeHidden();
    await expect(secondPage.locator("#edit-lease-banner")).toContainText("Bearbeitung für diese Sitzung reserviert");
    await expect(officeEditor(secondPage)).toHaveAttribute("contenteditable", "true");

    await expect(page.locator("#edit-lease-banner")).toContainText("Eine andere Sitzung bearbeitet diese Version", { timeout: 30000 });
    await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
    await expect(officeEditor(page)).toContainText("Unsaved first-session draft");
    await expect(page.locator("#document-save")).toBeDisabled();
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-edit-lease-first-${testInfo.project.name}.png`, fullPage: true });
    await secondPage.screenshot({ path: `${ARTIFACT_DIR}/office-edit-lease-takeover-${testInfo.project.name}.png`, fullPage: true });
    verifyFirst();
    verifySecond();
  } finally {
    await secondContext.close();
  }
});
