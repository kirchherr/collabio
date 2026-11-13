import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-font-size";
const sourceVersion = "stored-docx-font-size-v1";
const sizes = [24, 8, 12, 24, 48, 14, 10];

async function verifySizes(root) {
  const nodes = root.locator("[data-office-font-size]");
  await expect(nodes).toHaveText(["GROESSENKOPF", "GROESSE08", "GROESSE12", "GROESSE24", "GROESSE48", "TABELLENKOPF", "TABELLENTEXT"]);
  for (const [index, size] of sizes.entries()) {
    await expect(nodes.nth(index)).toHaveAttribute("data-office-font-size", String(size));
    const pixels = await nodes.nth(index).evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    expect(pixels).toBeCloseTo(size * 4 / 3, 1);
  }
  await expect(root.locator("strong")).toContainText("GROESSE12");
  await expect(root.locator("table th")).toHaveText("TABELLENKOPF");
}

test("Office imports explicit run font sizes from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Schriftgroessen");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifySizes(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  await openOfficeDocument(page, saved.document.object_id);
  await verifySizes(officeEditor(page));

  const prints = await installPrintProbe(page, { pdfName: `office-docx-font-size-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifySizes(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-font-size-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  expectPdfStructure(prints[0].pdf, ["H1", "P", "Table", "TH", "TD"]);
  expect(prints[0].layout.fontSizes.map((entry) => entry.points)).toEqual(sizes);
  for (const size of prints[0].layout.fontSizes) expect(size.pixels).toBeCloseTo(size.points * 4 / 3, 1);
});
