import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-font-family";
const sourceVersion = "stored-docx-font-family-v1";
const families = ["sans", "sans", "serif", "mono", "mono", "mono", "mono", "serif"];
const faces = ["Arial", "Arial", "Georgia", "Consolas", "Consolas", "Consolas", "Consolas", "Georgia"];
const firstFace = (css) => css.split(",")[0].replaceAll('"', "").trim();

async function verifyFamilies(root) {
  const nodes = root.locator("[data-office-font-family]");
  await expect(nodes).toHaveText(["FAMILIENKOPF", "SANSBELEG", "SERIFBELEG", "MONOBELEG", "IIIIIIII", "WWWWWWWW", "MONOKOPF", "SERIFZELLE"]);
  for (const [index, family] of families.entries()) {
    await expect(nodes.nth(index)).toHaveAttribute("data-office-font-family", family);
    expect(await nodes.nth(index).evaluate((element) => getComputedStyle(element).fontFamily).then(firstFace)).toBe(faces[index]);
  }
  await expect(nodes.nth(2)).toHaveAttribute("data-office-font-size", "18");
  await expect(nodes.nth(2)).toHaveAttribute("data-office-text-color", "red");
  expect(await nodes.nth(2).evaluate((element) => getComputedStyle(element).color)).toBe("rgb(185, 28, 28)");
  await expect(root.locator("strong")).toContainText("SERIFBELEG");
  await expect(root.locator("em")).toContainText("MONOBELEG");
  await expect(root.locator("table th")).toHaveText("MONOKOPF");
}

test("Office imports bounded direct font families from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Schriftfamilien");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_object_id).toBe(sourceId);
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyFamilies(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  await verifyFamilies(officeEditor(page));
  const prints = await installPrintProbe(page, { pdfName: `office-docx-font-family-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifyFamilies(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-font-family-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  // Chromium produces the PDF artifact asynchronously after the authorized read.
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["H1", "P", "Table", "TH", "TD"]);
  expect(prints[0].layout.fontFamilies.map((entry) => entry.family)).toEqual(families);
  expect(prints[0].layout.fontFamilies.map((entry) => firstFace(entry.css))).toEqual(faces);
});
