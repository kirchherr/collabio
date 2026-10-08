import { test, expect } from "@playwright/test";

import { ARTIFACT_DIR, monitorPage } from "./support.mjs";
import { officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import {
  applyParagraphFormat, createParagraphFixture, expectParagraphStyle, paragraph, paragraphBlocks, selectParagraphBlocks,
} from "./paragraph-helper.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

test("Office paragraph pagination remains exact through undo save reload and print", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page);
  const content = { type: "doc", content: [
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Zusammengehörige Überschrift" }] },
    paragraph("Dieser Absatz bleibt als vollständiger Block bei seiner Überschrift."),
    paragraph("Dieser Absatz beginnt verbindlich auf einer neuen Seite."),
  ] };
  const created = await createParagraphFixture(page, `Paragraph pagination ${testInfo.project.name}`, content);
  await openOffice(page); await openOfficeDocument(page, created.document.object_id);

  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, { keepWithNext: true });
  await selectParagraphBlocks(page, 1);
  await applyParagraphFormat(page, { keepLines: true });
  await selectParagraphBlocks(page, 2);
  await applyParagraphFormat(page, { keepLines: true, pageBreakBefore: true });
  await expectParagraphStyle(paragraphBlocks(page).nth(0), { keepWithNext: true });
  await expectParagraphStyle(paragraphBlocks(page).nth(1), { keepLines: true });
  await expectParagraphStyle(paragraphBlocks(page).nth(2), { keepLines: true, pageBreakBefore: true });
  await page.keyboard.press("Control+z");
  await expect(paragraphBlocks(page).nth(2)).not.toHaveAttribute("data-office-page-break-before");
  await page.keyboard.press("Control+Shift+z");
  await expect(paragraphBlocks(page).nth(2)).toHaveAttribute("data-office-page-break-before", "true");

  const saved = await saveOffice(page, { objectId: created.document.object_id });
  expect(saved.content.content[0].attrs).toEqual({ level: 2, keepWithNext: true });
  expect(saved.content.content[1].attrs).toEqual({ keepLines: true });
  expect(saved.content.content[2].attrs).toEqual({ keepLines: true, pageBreakBefore: true });
  expect((await officeContent(page, created.document.object_id, { versionId: created.version.version_id })).content).toEqual(content);
  await page.locator("#document-close").click(); await openOfficeDocument(page, created.document.object_id);
  await expectParagraphStyle(paragraphBlocks(page).nth(2), { keepLines: true, pageBreakBefore: true });

  const prints = await installPrintProbe(page, { pdfName: `office-paragraph-pagination-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview h2")).toHaveAttribute("data-office-keep-with-next", "true");
  await expect(page.locator("#print-preview p").nth(2)).toHaveAttribute("data-office-page-break-before", "true");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-paragraph-pagination-${testInfo.project.name}.png`, fullPage: true });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1);
  await expect.poll(() => prints[0].pdf).not.toBeNull();
  expect([...prints[0].pdf.toString("latin1").matchAll(/\/Type\s*\/Page\b/g)].length).toBeGreaterThanOrEqual(2);
  verifyBrowser();
});
