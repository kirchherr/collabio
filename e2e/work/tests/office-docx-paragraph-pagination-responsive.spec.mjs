import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-paragraph-pagination";
const sourceVersion = "stored-docx-paragraph-pagination-v1";

async function verifyPagination(root) {
  await expect(root.locator('h1[data-office-keep-with-next="false"][data-office-keep-lines="false"]')).toHaveText("PAGINIERUNGSBELEG");
  await expect(root.locator('h2[data-office-keep-with-next="false"]')).toHaveText("CONTROL-TITLE");
  await expect(root.locator('h2[data-office-keep-with-next="true"]')).toHaveText("KEPT-TITLE");
  await expect(root.locator('p[data-office-keep-lines="true"]')).toContainText("KEPT-LINE-08");
  await expect(root.locator('p[data-office-keep-lines="false"]')).toContainText("CONTROL-LINE-08");
  await expect(root.locator('[data-office-page-break-before="true"]')).toHaveCount(2);
}

test("Office imports paragraph keeping controls from a stored DOCX", async ({ page }, testInfo) => {
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
  const select = dialog.locator("#import-source-select");
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Absatzzusammenhalt");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyPagination(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(exact.content.content[0].attrs).toMatchObject({ keepWithNext: false, keepLines: false });
  expect(exact.content.content[5].attrs).toMatchObject({ keepWithNext: true });
  expect(exact.content.content[6].attrs).toMatchObject({ keepWithNext: false, keepLines: true });
  await openOfficeDocument(page, saved.document.object_id);
  await verifyPagination(officeEditor(page));

  const prints = await installPrintProbe(page, { pdfName: `office-docx-paragraph-pagination-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifyPagination(print);
  await print.locator('h2[data-office-keep-with-next="true"]').screenshot({ path: `${ARTIFACT_DIR}/office-docx-paragraph-pagination-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  expectPdfStructure(prints[0].pdf, ["H1", "H2", "P"]);
  expect(prints[0].layout.paragraphPagination).toHaveLength(5);
  for (const node of prints[0].layout.paragraphPagination) {
    if (node.keepWithNext === "false") expect(node.breakAfter).toBe("auto");
    if (node.keepWithNext === "true") expect(["avoid", "avoid-page"]).toContain(node.breakAfter);
    if (node.keepLines === "false") expect(node.breakInside).toBe("auto");
    if (node.keepLines === "true") expect(["avoid", "avoid-page"]).toContain(node.breakInside);
  }
});
