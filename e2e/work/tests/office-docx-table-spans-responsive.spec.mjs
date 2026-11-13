import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-table-spans";
const sourceVersion = "stored-docx-table-spans-v1";
const geometry = (doc) => doc.content[1].content.map((row) =>
  row.content.map((cell) => [cell.attrs?.colspan ?? 1, cell.attrs?.rowspan ?? 1]));

async function verifyTable(table) {
  await expect(table.locator("tr")).toHaveCount(3);
  await expect(table.locator("tr").first().locator('td[colspan="2"][rowspan="2"]')).toHaveText("Verbundene Gruppe");
  await expect(table.locator("tr").nth(1).locator("td")).toHaveText(["Rechts unten"]);
  await expect(table.locator("tr").last().locator('td[colspan="2"]')).toHaveText("Quer verbunden");
}

test("Office imports both merged cell directions from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(dialog.locator("#import-source-select")).toContainText("Synthetische gespeicherte DOCX-Quelle mit Zellspannen");
  await dialog.locator("#import-source-select").selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyTable(officeEditor(page).locator("table"));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(geometry(exact.content)).toEqual(geometry(preview.document));
  await openOfficeDocument(page, saved.document.object_id);
  const table = officeEditor(page).locator("table");
  await verifyTable(table);
  await table.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-table-spans-${testInfo.project.name}.png`, fullPage: true });

  const prints = await installPrintProbe(page, { pdfName: `office-docx-table-spans-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await verifyTable(page.locator("#print-preview table"));
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["Table", "TR", "TD"]);
});
