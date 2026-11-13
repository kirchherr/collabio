import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-paragraph-spacing";
const sourceVersion = "stored-docx-paragraph-spacing-v1";
const spacing = [
  { spacingBefore: 0, spacingAfter: 12, lineSpacing: "1.15" },
  { spacingBefore: 0, spacingAfter: 0, lineSpacing: "1" },
  { spacingBefore: 12, spacingAfter: 6, lineSpacing: "2" },
  { spacingBefore: 0, spacingAfter: 0, lineSpacing: "1" },
  { spacingBefore: 24, spacingAfter: 0, lineSpacing: "1.5" },
];

async function verifySpacing(root) {
  const nodes = root.locator("h1[data-office-line-spacing],p[data-office-line-spacing]");
  await expect(nodes).toHaveText(["ABSTANDKOPF", "EINFACH1 EINFACH2", "DOPPELT1 DOPPELT2", "DANACH", "ABSTAND24 ZEILEN15"]);
  for (const [index, attrs] of spacing.entries()) {
    const node = nodes.nth(index);
    await expect(node).toHaveAttribute("data-office-spacing-before", String(attrs.spacingBefore));
    await expect(node).toHaveAttribute("data-office-spacing-after", String(attrs.spacingAfter));
    await expect(node).toHaveAttribute("data-office-line-spacing", attrs.lineSpacing);
    const actual = await node.evaluate((element) => {
      const style = getComputedStyle(element);
      return { before: parseFloat(style.marginTop), after: parseFloat(style.marginBottom), ratio: parseFloat(style.lineHeight) / parseFloat(style.fontSize) };
    });
    expect(actual.before).toBeCloseTo(attrs.spacingBefore * 4 / 3, 1);
    expect(actual.after).toBeCloseTo(attrs.spacingAfter * 4 / 3, 1);
    expect(actual.ratio).toBeCloseTo(Number(attrs.lineSpacing), 2);
  }
}

test("Office imports direct paragraph spacing from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Absatzabstaenden");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifySpacing(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(exact.content.content.map((node) => {
    const { spacingBefore, spacingAfter, lineSpacing } = node.attrs;
    return { spacingBefore, spacingAfter, lineSpacing };
  })).toEqual(spacing);
  await openOfficeDocument(page, saved.document.object_id);
  const editor = officeEditor(page);
  await verifySpacing(editor);

  const prints = await installPrintProbe(page, { pdfName: `office-docx-paragraph-spacing-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifySpacing(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-paragraph-spacing-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  expectPdfStructure(prints[0].pdf, ["H1", "P"]);
});
