import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-paragraph-alignment";
const sourceVersion = "stored-docx-paragraph-alignment-v1";
const alignments = ["center", "left", "center", "right", "justify"];

async function verifyAlignment(root) {
  const nodes = root.locator("h1[data-office-align],p[data-office-align]");
  await expect(nodes).toHaveText(["MITTEKOPF", "LINKSBELEG", "MITTEBELEG", "RECHTSBELEG", /^BLOCKBEGIN .* BLOCKENDE$/]);
  for (const [index, alignment] of alignments.entries()) {
    await expect(nodes.nth(index)).toHaveAttribute("data-office-align", alignment);
    await expect(nodes.nth(index)).toHaveCSS("text-align", alignment);
  }
}

test("Office imports direct paragraph alignment from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(sourceSelect).toContainText("Synthetische gespeicherte DOCX-Quelle mit Absatzausrichtung");
  await sourceSelect.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyAlignment(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(exact.content.content.map((node) => node.attrs.textAlign)).toEqual(alignments);
  await openOfficeDocument(page, saved.document.object_id);
  const editor = officeEditor(page);
  await verifyAlignment(editor);
  await editor.screenshot({ path: `${ARTIFACT_DIR}/office-docx-paragraph-alignment-${testInfo.project.name}.png` });

  const prints = await installPrintProbe(page, { pdfName: `office-docx-paragraph-alignment-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await verifyAlignment(page.locator("#print-preview"));
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["H1", "P"]);
});
