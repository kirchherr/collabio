import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-table-header";
const sourceVersion = "stored-docx-table-header-v1";

test("Office imports the repeating first row from a stored DOCX", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  const denied = await page.request.post(`${BASE_URL}/v1/office/documents/import-previews`, {
    headers: { ...OFFICE_READER_HEADERS, "X-Readable-Object-Ids": sourceId },
    data: { source_object_id: sourceId, source_version_id: sourceVersion },
  });
  expect(denied.status()).toBe(403);
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  await page.locator("#document-import").click();
  const dialog = page.locator("#import-document-dialog");
  const sourceSelect = dialog.locator("#import-source-select");
  await expect(sourceSelect).toContainText("Synthetische gespeicherte DOCX-Quelle mit Tabellenkopf");
  await sourceSelect.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await expect(officeEditor(page).locator("table tr").first().locator("th")).toHaveText(["KOPFBELEG", "Bezeichnung"]);
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  const rows = officeEditor(page).locator("table tr");
  await expect(rows).toHaveCount(55);
  await expect(rows.first().locator("th")).toHaveText(["KOPFBELEG", "Bezeichnung"]);
  await expect(rows.last().locator("td")).toHaveText(["ZEILE-054", "Eintrag 054"]);
  await rows.first().screenshot({ path: `${ARTIFACT_DIR}/office-docx-table-header-${testInfo.project.name}.png` });

  const prints = await installPrintProbe(page, { pdfName: `office-docx-table-header-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator('#print-preview table thead th[scope="col"]')).toHaveText(["KOPFBELEG", "Bezeichnung"]);
  await expect(page.locator("#print-preview table tbody tr")).toHaveCount(54);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["Table", "TR", "TH", "TD"]);
});
