import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-lists";
const sourceVersion = "stored-docx-lists-v1";
const starts = (document) => document.content.filter((node) => node.type === "orderedList").map((node) => node.attrs.start);

test("Office imports stored DOCX list levels and numbering continuity", async ({ page }, testInfo) => {
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
  await expect(dialog.locator("#import-source-select")).toContainText("Synthetische gespeicherte DOCX-Quelle mit Listen");
  await dialog.locator("#import-source-select").selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  expect(starts(preview.document)).toEqual([4, 6, 9, 7]);
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(starts(exact.content)).toEqual([4, 6, 9, 7]);
  expect(exact.content.content[0]).toEqual(preview.document.content[0]);
  await openOfficeDocument(page, saved.document.object_id);
  const editor = officeEditor(page);
  const rootLists = editor.locator(":scope > ol");
  const values = (nodes) => nodes.map((node) => node.start);
  await expect(rootLists).toHaveCount(4);
  expect(await rootLists.evaluateAll(values)).toEqual([4, 6, 9, 7]);
  expect(await rootLists.first().locator("ul ol").evaluateAll(values)).toEqual([3, 3]);
  await editor.getByText("Vierter Tiefenpunkt").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-lists-${testInfo.project.name}.png`, fullPage: true });
  const prints = await installPrintProbe(page, { pdfName: `office-docx-lists-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const printLists = page.locator("#print-preview .office-print-content > ol");
  expect(await printLists.evaluateAll(values)).toEqual([4, 6, 9, 7]);
  expect(await printLists.first().locator("ul ol").evaluateAll(values)).toEqual([3, 3]);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
});
