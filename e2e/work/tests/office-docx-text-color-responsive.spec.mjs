import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-text-color";
const sourceVersion = "stored-docx-text-color-v1";
const colors = ["black", "slate", "red", "orange", "green", "teal", "blue", "purple"];
const rgbs = ["rgb(17, 24, 39)", "rgb(71, 85, 105)", "rgb(185, 28, 28)", "rgb(154, 52, 18)", "rgb(22, 101, 52)", "rgb(17, 94, 89)", "rgb(29, 78, 216)", "rgb(126, 34, 206)"];

async function verifyColors(root) {
  const nodes = root.locator("[data-office-text-color]");
  await expect(nodes).toHaveText(["SCHWARZ", "SCHIEFER", "ROT", "ORANGE", "GRUEN", "PETROL", "BLAU", "VIOLETT"]);
  for (const [index, color] of colors.entries()) {
    await expect(nodes.nth(index)).toHaveAttribute("data-office-text-color", color);
    expect(await nodes.nth(index).evaluate((element) => getComputedStyle(element).color)).toBe(rgbs[index]);
  }
  await expect(nodes.nth(0)).toHaveAttribute("data-office-font-size", "24");
  await expect(nodes.nth(2)).toHaveAttribute("data-office-font-size", "18");
  await expect(root.locator("strong")).toContainText("ROT");
  await expect(root.locator("em")).toContainText("ORANGE");
  await expect(root.locator("table th")).toHaveText("BLAU");
}

test("Office imports exact native palette text colors from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Textfarben");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_object_id).toBe(sourceId);
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyColors(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  await verifyColors(officeEditor(page));
  const prints = await installPrintProbe(page, { pdfName: `office-docx-text-color-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifyColors(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-text-color-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  // Chromium produces the PDF artifact asynchronously after the authorized read.
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["H1", "P", "Table", "TH", "TD"]);
  expect(prints[0].layout.textColors).toEqual(colors.map((color, index) => ({ color, rgb: rgbs[index] })));
});
