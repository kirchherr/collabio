import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-running";
const sourceVersion = "stored-docx-running-v1";
const header = 'DOCX Header "literal"';
const profiles = [
  { header, footer: "DOCX Footer Alpha", numbering: "none" },
  { header, footer: "DOCX Footer Beta", numbering: "none" },
  { header: "", footer: "DOCX Footer Beta", numbering: "none" },
];
const running = (document) => [document.attrs.running,
  ...document.content.filter((node) => node.type === "sectionBreak").map((node) => node.attrs.running)];

test("Office imports stored DOCX running text and prints inherited and cleared defaults", async ({ page }, testInfo) => {
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
  const source = dialog.locator("#import-source-select");
  await expect(source).toContainText("Synthetische gespeicherte DOCX-Quelle mit Kopf- und Fußzeilen");
  await source.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  expect(running(preview.document)).toEqual(profiles);
  await expect(officeEditor(page)).toContainText("DOCX Body Three");
  await expect(officeEditor(page)).not.toContainText(header);
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(running(exact.content)).toEqual(profiles);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  const markers = officeEditor(page).locator(".office-section-break");
  await expect(markers).toHaveCount(2);
  for (let index = 0; index < 2; index += 1) {
    await markers.nth(index).click();
    await page.locator("#insert-menu").selectOption("editSectionBreak");
    await expect(page.locator("#section-header")).toHaveValue(profiles[index + 1].header);
    await expect(page.locator("#section-footer")).toHaveValue(profiles[index + 1].footer);
    if (index === 0) {
      await page.locator("#section-header").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-running-${testInfo.project.name}.png`, fullPage: true });
    }
    await page.locator("#section-cancel").click();
  }
  const prints = await installPrintProbe(page, { pdfName: `office-docx-running-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  expect([...prints[0].pdf.toString("latin1").matchAll(/\/Type\s*\/Page\b/g)]).toHaveLength(3);
});
