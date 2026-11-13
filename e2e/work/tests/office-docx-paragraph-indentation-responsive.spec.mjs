import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, waitForOfficePrintPdf, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-paragraph-indentation";
const sourceVersion = "stored-docx-paragraph-indentation-v1";
const indentation = [
  { indentLeft: 18 },
  { indentLeft: 0, indentRight: 0, specialIndent: "none" },
  { indentLeft: 36, indentRight: 18 },
  { indentLeft: 0, indentRight: 0 },
  { indentLeft: 0, indentRight: 36 },
  { indentLeft: 18, indentRight: 0, specialIndent: "firstLine36" },
  { indentLeft: 18, indentRight: 0, specialIndent: "hanging18" },
];

async function verifyIndentation(root) {
  const nodes = root.locator("h1[data-office-indent-left],p[data-office-indent-left]");
  await expect(nodes).toHaveText(["EINZUGKOPF", "BASISLINKS", "LINKSEINZUG", "RECHTSBASIS", "RECHTSEINZUG", "ERSTZEILE FOLGEZEILE", "HAENGEERSTE HAENGEFOLGE"]);
  for (const [index, attrs] of indentation.entries()) {
    const node = nodes.nth(index);
    await expect(node).toHaveAttribute("data-office-indent-left", String(attrs.indentLeft));
    if (attrs.indentRight !== undefined) await expect(node).toHaveAttribute("data-office-indent-right", String(attrs.indentRight));
    if (attrs.specialIndent !== undefined) await expect(node).toHaveAttribute("data-office-special-indent", attrs.specialIndent);
    const actual = await node.evaluate((element) => {
      const style = getComputedStyle(element);
      return { left: parseFloat(style.marginInlineStart), right: parseFloat(style.marginInlineEnd), padding: parseFloat(style.paddingInlineStart), first: parseFloat(style.textIndent) };
    });
    expect(actual.left).toBeCloseTo(attrs.indentLeft * 4 / 3, 1);
    if (attrs.indentRight !== undefined) expect(actual.right).toBeCloseTo(attrs.indentRight * 4 / 3, 1);
    if (attrs.specialIndent === "firstLine36") expect(actual.first).toBeCloseTo(48, 1);
    if (attrs.specialIndent === "hanging18") {
      expect(actual.padding).toBeCloseTo(24, 1);
      expect(actual.first).toBeCloseTo(-24, 1);
    }
  }
}

test("Office imports direct paragraph indentation from a stored DOCX", async ({ page }, testInfo) => {
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
  await expect(select).toContainText("Synthetische gespeicherte DOCX-Quelle mit Absatzeinzuegen");
  await select.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await verifyIndentation(officeEditor(page));
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  for (const [index, attrs] of indentation.entries()) expect(exact.content.content[index].attrs).toMatchObject(attrs);
  await openOfficeDocument(page, saved.document.object_id);
  await verifyIndentation(officeEditor(page));

  const prints = await installPrintProbe(page, { pdfName: `office-docx-paragraph-indentation-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const print = page.locator("#print-preview");
  await verifyIndentation(print);
  await print.screenshot({ path: `${ARTIFACT_DIR}/office-docx-paragraph-indentation-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await waitForOfficePrintPdf(prints);
  expectPdfStructure(prints[0].pdf, ["H1", "P"]);
});
