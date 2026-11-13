import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const SOURCE = "work-e2e-stored-docx", VERSION = "stored-docx-v1";

test("Office imports a real stored DOCX through discovery and the isolated socket parser", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  // No request interception: storage, ACL resolution, parser, editing and save are real.
  const denied = await page.request.post(`${BASE_URL}/v1/office/documents/import-previews`, {
    headers: { ...OFFICE_READER_HEADERS, "X-Readable-Object-Ids": SOURCE },
    data: { source_object_id: SOURCE, source_version_id: VERSION },
  });
  expect(denied.status()).toBe(403);
  const hidden = await page.request.get(`${BASE_URL}/v1/office/documents/import-sources?query=${SOURCE}`, { headers: OFFICE_READER_HEADERS });
  expect(hidden.status()).toBe(200);
  expect((await hidden.json()).items).toEqual([]);
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  const discovery = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-sources");
  await page.locator("#document-import").click();
  expect((await discovery).status()).toBe(200);
  const dialog = page.locator("#import-document-dialog");
  await expect(dialog.locator("#import-source-select")).toContainText("Synthetische gespeicherte DOCX-Quelle");
  await dialog.locator("#import-source-select").selectOption(`${SOURCE}\u001f${VERSION}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const preview = await response.json();
  expect(preview.source_object_id).toBe(SOURCE);
  expect(preview.source_version_id).toBe(VERSION);
  expect(preview.content_persisted).toBe(false);
  expect(preview.save_requires_explicit_confirmation).toBe(true);
  expect(preview.source_content_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
  await expect(officeEditor(page).locator("h1 strong")).toHaveText("Gespeicherte Quelle im echten Parser");
  await expect(officeEditor(page).locator(".office-page-break")).toHaveCount(1);
  await expect(officeEditor(page).locator("table")).toContainText("Exakte Version");
  await expect(page.locator("#document-classification")).toHaveValue("confidential");
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  const persisted = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(persisted.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(saved.document.information_classification).toBe("confidential");
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page)).toContainText("Nach dem Seitenwechsel");
  const sourceAgain = await page.request.post(`${BASE_URL}/v1/office/documents/import-previews`, {
    headers: OFFICE_HEADERS, data: { source_object_id: SOURCE, source_version_id: VERSION },
  });
  expect(sourceAgain.status()).toBe(200);
  expect((await sourceAgain.json()).source_content_hash).toBe(preview.source_content_hash);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await officeEditor(page).locator("h1").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-stored-docx-${testInfo.project.name}.png`, fullPage: true });
});
