import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-vertical-position";
const sourceVersion = "stored-docx-vertical-position-v1";
const positions = ["superscript", "subscript", "superscript", "superscript", "subscript"];

async function verifyPositions(root) {
  const nodes = root.locator("[data-office-vertical-position]");
  await expect(nodes).toHaveText(["HOCHBELEG", "TIEFBELEG", "MISCHBELEG", "KOPFHOCH", "ZELLTIEF"]);
  for (const [index, position] of positions.entries()) {
    await expect(nodes.nth(index)).toHaveAttribute("data-office-vertical-position", position);
    expect(await nodes.nth(index).evaluate((element) => getComputedStyle(element).verticalAlign)).toBe(position === "superscript" ? "super" : "sub");
  }
  for (const text of ["GRUNDBELEG", "NORMALBELEG"]) {
    const baseline = root.locator('[data-office-font-size="12"]').filter({ hasText: new RegExp("^" + text + "$") });
    await expect(baseline).toHaveCount(1);
    expect(await baseline.getAttribute("data-office-vertical-position")).toBeNull();
    expect(await baseline.evaluate((element) => getComputedStyle(element).verticalAlign)).toBe("baseline");
  }
  await expect(nodes.nth(2)).toHaveAttribute("data-office-font-family", "mono");
  await expect(nodes.nth(2)).toHaveAttribute("data-office-font-size", "14");
  await expect(nodes.nth(2)).toHaveAttribute("data-office-text-color", "blue");
  await expect(root.locator("strong")).toContainText("HOCHBELEG");
  await expect(root.locator("em")).toContainText("TIEFBELEG");
  await expect(root.locator("table th")).toHaveText("KOPFHOCH");
}

test("Office imports bounded direct vertical positions from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Zeichenlagen");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_object_id).toBe(sourceId);
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyPositions(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  await verifyPositions(officeEditor(page));
  const prints = await installPrintProbe(page, { pdfName: `office-docx-vertical-position-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifyPositions(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-vertical-position-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  // Chromium produces the PDF artifact asynchronously after the authorized read.
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["H1", "P", "Table", "TH", "TD"]);
  expect(prints[0].layout.verticalPositions).toEqual(positions.map((position) => ({ position, css: position === "superscript" ? "super" : "sub" })));

});
