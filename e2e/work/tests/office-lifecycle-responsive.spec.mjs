import { expect, test } from "@playwright/test";

import { BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, openOffice } from "./office-support.mjs";

test("Office lifecycle explains draft, collaboration, saved version and closed record transitions", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const saved = await createOfficeDocument(page, `Synthetic lifecycle ${testInfo.project.name}`, "Saved lifecycle text");
  await expect(page.locator("#edit-lease-banner")).toContainText("Bearbeitung für diese Sitzung reserviert");
  await officeEditor(page).fill("Unsaved lifecycle draft");

  const lifecycle = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/v1/office/documents/${saved.document.object_id}/lifecycle` && response.request().method() === "GET";
  });
  await page.locator("#document-lifecycle").click();
  expect((await lifecycle).status()).toBe(200);
  await expect(page.locator("#lifecycle-dialog")).toBeVisible();
  await expect(page.locator("#lifecycle-draft")).toContainText("ungespeicherte Änderungen vorhanden");
  await expect(page.locator("#lifecycle-collaborative")).toContainText("für diese Sitzung reserviert");
  await expect(page.locator("#lifecycle-saved")).toContainText(saved.version.version_id);
  await expect(page.locator("#lifecycle-business")).toContainText("Übergang geschlossen");
  await expect(page.locator("#lifecycle-worm")).toContainText("kein WORM Evidence Record");
  await expect(page.locator("#lifecycle-status")).toContainText("AI darf keinen Business Record auslösen");
  await expect(officeEditor(page)).toContainText("Unsaved lifecycle draft");
  await page.locator("#lifecycle-done").click();
  await expect(page.locator("#lifecycle-dialog")).toBeHidden();
  verify();
});
