import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-sections";
const sourceVersion = "stored-docx-sections-v1";
const rootPage = {
  paper: "a4", orientation: "portrait", margins: { top: 20, right: 12, bottom: 22, left: 14 },
};
const sectionPage = {
  paper: "letter", orientation: "landscape", columns: "two",
  margins: { top: 18, right: 16, bottom: 20, left: 18 },
};

test("Office imports and prints the ordered profiles of a real stored DOCX", async ({ page }, testInfo) => {
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
  await expect(source).toContainText("Synthetische gespeicherte DOCX-Quelle mit Abschnitten");
  await source.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  expect(preview.document.attrs.page).toEqual(rootPage);
  expect(preview.document.content.map((node) => node.type)).toEqual(["paragraph", "sectionBreak", "paragraph"]);
  expect(preview.document.content[1].attrs.page).toEqual(sectionPage);
  await expect(officeEditor(page).locator(".office-section-break")).toHaveCount(1);
  await expect(page.locator("#document-classification")).toHaveValue("confidential");
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content.attrs.page).toEqual(rootPage);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.content[1]).toEqual(preview.document.content[1]);

  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page)).toContainText("Erster Abschnitt auf A4");
  await expect(officeEditor(page)).toContainText("Zweiter Abschnitt auf Letter");
  const marker = officeEditor(page).locator(".office-section-break");
  await marker.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await marker.click();
  await page.locator("#insert-menu").selectOption("editSectionBreak");
  await expect(page.locator("#section-description")).toContainText("Letter · Querformat · 2 Spalten");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-sections-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#section-cancel").click();

  const prints = await installPrintProbe(page, { pdfName: `office-docx-sections-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator('#print-preview .office-print-content[data-office-columns="two"]')).toHaveCount(1);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  const pdf = prints[0].pdf.toString("latin1");
  const boxes = [...pdf.matchAll(/\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/g)]
    .map((match) => [Number(match[1]), Number(match[2])]);
  expect([...pdf.matchAll(/\/Type\s*\/Page\b/g)]).toHaveLength(2);
  expect(boxes).toHaveLength(2);
  for (const [index, [width, height]] of [[595, 842], [792, 612]].entries()) {
    expect(Math.abs(boxes[index][0] - width)).toBeLessThan(2);
    expect(Math.abs(boxes[index][1] - height)).toBeLessThan(2);
  }
});
