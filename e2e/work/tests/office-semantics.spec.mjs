import { expect, test } from "@playwright/test";

import { monitorPage, BASE_URL } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { expectPdfStructure, installPrintProbe, pdfPageCount, submitOfficePrint } from "./office-print-support.mjs";

async function openStructure(page, kind) {
  await page.locator("#semantic-options").click();
  await expect(page.locator("#semantic-dialog")).toBeVisible();
  await page.locator("#semantic-kind").selectOption(kind);
}

test("Office semantic structures save exact catalogs, nodes, derived labels and undo", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic semantic document", { text: "Overview" });
  await page.locator("#text-style").selectOption("heading-1");
  await officeEditor(page).press("Control+End");

  await openStructure(page, "field");
  await page.locator("#semantic-field-key").fill("project");
  await page.locator("#semantic-field-label").fill("Project");
  await page.locator("#semantic-field-value").fill("Apollo");
  await page.locator("#semantic-apply").click();
  await expect(officeEditor(page).locator(".office-documentField")).toHaveText("Apollo");

  await openStructure(page, "footnote");
  await page.locator("#semantic-note-text").fill("Primary evidence");
  await page.locator("#semantic-apply").click();
  await expect(officeEditor(page).locator(".office-noteReference")).toHaveText("Fußnote 1");
  await openStructure(page, "endnote");
  await page.locator("#semantic-note-text").fill("Closing evidence");
  await page.locator("#semantic-apply").click();
  await expect(officeEditor(page).locator(".office-noteReference")).toHaveCount(2);
  await expect(officeEditor(page).locator(".office-noteReference").last()).toHaveText("Endnote 1");

  await openStructure(page, "source");
  await page.locator("#semantic-source-author").fill("Ada Lovelace");
  await page.locator("#semantic-source-title").fill("Notes on the Analytical Engine");
  await page.locator("#semantic-source-year").fill("1843");
  await page.locator("#semantic-apply").click();
  await openStructure(page, "citation");
  await page.locator("#semantic-source-id").selectOption({ index: 1 });
  await page.locator("#semantic-citation-locator").fill("p. 12");
  await page.locator("#semantic-apply").click();
  await expect(officeEditor(page).locator(".office-citationReference")).toHaveText("[Ada Lovelace, 1843, p. 12]");

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await openStructure(page, "equation");
  await page.locator("#semantic-equation-source").fill("E = mc^2");
  await page.locator("#semantic-equation-alt").fill("Energy equals mass times the speed of light squared");
  await page.locator("#semantic-apply").click();
  await expect(officeEditor(page).locator(".office-equation")).toHaveText("E = mc^2");
  await page.locator('[data-command="undo"]').click();
  await expect(officeEditor(page).locator(".office-equation")).toHaveCount(0);
  await page.locator('[data-command="redo"]').click();

  for (const [kind, selector] of [["toc", ".office-tableOfContents"], ["bibliography", ".office-bibliography"], ["index", ".office-referenceIndex"]]) {
    await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
    await openStructure(page, kind); await page.locator("#semantic-apply").click();
    await expect(officeEditor(page).locator(selector)).toHaveCount(1);
  }

  const saved = await saveOffice(page);
  expect(saved.content.attrs.documentFields).toEqual([{ key: "project", label: "Project", value: "Apollo" }]);
  expect(saved.content.attrs.citationSources).toHaveLength(1);
  await page.locator("#document-close").click(); await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator(".office-documentField")).toHaveText("Apollo");
  await expect(officeEditor(page).locator(".office-equation")).toHaveText("E = mc^2");
  await expect(officeEditor(page).locator(".office-tableOfContents")).toContainText("Overview");
  await expect(officeEditor(page).locator(".office-bibliography")).toContainText("Notes on the Analytical Engine");
  await expect(officeEditor(page).locator(".office-referenceIndex")).toContainText("equation");
  await openStructure(page, "field"); await page.locator("#semantic-field-key").fill("project");
  await page.locator("#semantic-remove").click();
  await expect(officeEditor(page).locator(".office-documentField")).toHaveAttribute("data-office-broken", "");
  await page.locator('[data-command="undo"]').click();
  await expect(officeEditor(page).locator(".office-documentField")).toHaveText("Apollo");
  await openStructure(page, "citation"); await page.locator("#semantic-source-id").selectOption({ index: 1 });
  await page.locator("#semantic-remove").click();
  await expect(officeEditor(page).locator(".office-citationReference")).toHaveAttribute("data-office-broken", "");
  await page.locator('[data-command="undo"]').click();
  await expect(officeEditor(page).locator(".office-citationReference")).toContainText("Ada Lovelace");
  const printCalls = await installPrintProbe(page, { pdfName: "office-semantics-a4.pdf" });
  await page.locator("#document-print").click(); await expect(page.locator("#print-dialog")).toBeVisible();
  await expect(page.locator("#print-preview .office-print-toc")).toContainText("Overview");
  await expect(page.locator("#print-preview .office-print-footnotes")).toContainText("Primary evidence");
  await expect(page.locator("#print-preview .office-print-endnotes")).toContainText("Closing evidence");
  await expect(page.locator("#print-preview .office-print-bibliography")).toContainText("Notes on the Analytical Engine");
  await expect(page.locator("#print-preview .office-print-equation")).toContainText("E = mc^2");
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  expect(printCalls).toHaveLength(1); expect(printCalls[0].pdf).not.toBeNull();
  expect(pdfPageCount(printCalls[0].pdf, 595.28, 841.89)).toBeGreaterThan(0);
  expectPdfStructure(printCalls[0].pdf, ["H1", "H2", "L", "LI", "Code", "Figure"]);
  await page.locator("#print-close").click();
  expect((await officeContent(page, saved.document.object_id)).content).toEqual(saved.content);
  expect(await officeVersions(page, saved.document.object_id)).toHaveLength(1);
  verifyBrowser();
});
