import { test, expect } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { createOfficeDocument, OFFICE_HEADERS, officeContent, officeEditor, openOffice, saveOffice } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });

async function fixture(page) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Section profile proof", "BeforeAfter");
  const response = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS,
    data: { title: first.version.title, document: { type: "doc", content: [p("BeforeAfter"), p("Following block")] },
      mutation_reference: `section-fixture-${first.version.version_id}`,
      expected_current_version_id: first.version.version_id, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  const saved = await response.json(); await page.locator("#document-reload").click();
  await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
  return saved;
}

async function caret(page, selector, offset) {
  await officeEditor(page).locator(selector).click();
  await officeEditor(page).locator(selector).evaluate(async (element, position) => {
    element.closest('[contenteditable="true"]').focus();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const text = document.createTreeWalker(element, NodeFilter.SHOW_TEXT).nextNode();
    const range = document.createRange(); range.setStart(text, position); range.collapse(true);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, offset);
}

test("Office sections insert edit undo save print and remove exact responsive profiles", async ({ page }, testInfo) => {
  const baseline = await fixture(page), editor = officeEditor(page), marker = editor.locator(".office-section-break");
  await caret(page, "p:first-child", 6);
  await page.locator("#insert-menu").selectOption("sectionBreak");
  await expect(page.locator("#section-dialog")).toBeVisible();
  await page.locator("#section-paper").selectOption("letter");
  await page.locator("#section-orientation").selectOption("landscape");
  await page.locator("#section-top").fill("20"); await page.locator("#section-right").fill("12");
  await page.locator("#section-bottom").fill("22"); await page.locator("#section-left").fill("14");
  await page.locator("#section-header").fill("Appendix"); await page.locator("#section-footer").fill("Internal");
  await page.locator("#section-numbering").selectOption("pageOfPages");
  await expect(page.locator("#section-description")).toContainText("Letter · Querformat");
  const dialog = page.locator("#section-dialog");
  const dialogBox = await dialog.boundingBox();
  expect(dialogBox).not.toBeNull();
  expect(dialogBox.x).toBeGreaterThanOrEqual(0); expect(dialogBox.y).toBeGreaterThanOrEqual(0);
  expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-section-dialog-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#section-apply").click(); await expect(marker).toHaveCount(1);
  await page.keyboard.press("Control+z"); await expect(marker).toHaveCount(0);
  await page.keyboard.press("Control+Shift+z"); await expect(marker).toHaveCount(1);
  await marker.click(); await expect(marker).toHaveClass(/ProseMirror-selectednode/);
  await expect(page.locator('#insert-menu option[value="editSectionBreak"]')).toBeEnabled();
  await page.locator("#insert-menu").selectOption("editSectionBreak");
  await expect(page.locator("#section-header")).toHaveValue("Appendix");
  await page.locator("#section-header").fill("Appendix revised");
  await page.locator("#section-apply").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-sections-${testInfo.project.name}.png`, fullPage: true });
  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  expect(saved.content.content.map((node) => node.type)).toEqual(["paragraph", "sectionBreak", "paragraph", "paragraph"]);
  expect(saved.content.content[1].attrs).toEqual({ page: { paper: "letter", orientation: "landscape",
    margins: { top: 20, right: 12, bottom: 22, left: 14 } },
  running: { header: "Appendix revised", footer: "Internal", numbering: "pageOfPages" } });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content.content)
    .toEqual([p("BeforeAfter"), p("Following block")]);
  const prints = await installPrintProbe(page, { pdfName: `office-sections-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview .office-section-break")).toHaveCount(1);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1); expect(prints[0].snapshot.ready).toBe(true);
  await expect.poll(() => prints[0].pdf).not.toBeNull();
  const mediaBoxes = [...prints[0].pdf.toString("latin1")
    .matchAll(/\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/g)]
    .map((match) => [Number(match[1]), Number(match[2])]);
  expect(mediaBoxes.some(([width, height]) => Math.abs(width - 595) < 2 && Math.abs(height - 842) < 2)).toBe(true);
  expect(mediaBoxes.some(([width, height]) => Math.abs(width - 792) < 2 && Math.abs(height - 612) < 2)).toBe(true);
  expect([...prints[0].pdf.toString("latin1").matchAll(/\/Type\s*\/Page\b/g)].length).toBe(2);
  expect(prints[0].snapshot.html).toContain("office-print-section-01");
  expect(prints[0].snapshot.html).toContain('data-office-section="1"');
  await page.locator("#print-close").click();
  await marker.click(); await page.locator("#insert-menu").selectOption("removeSectionBreak");
  await expect(marker).toHaveCount(0); await page.keyboard.press("Control+z"); await expect(marker).toHaveCount(1);
});

test("Office section dialog rejects incompatible margins without mutating the draft", async ({ page }) => {
  await fixture(page); await caret(page, "p:first-child", 6);
  await page.locator("#insert-menu").selectOption("sectionBreak");
  await page.locator("#section-header").fill("Needs space"); await page.locator("#section-top").fill("15");
  await expect(page.locator("#section-apply")).toBeDisabled();
  await expect(page.locator("#section-status")).toContainText("mindestens 16 mm");
  await page.locator("#section-cancel").click();
  await expect(officeEditor(page).locator(".office-section-break")).toHaveCount(0);
  await expect(page.locator("#document-save")).toBeDisabled();
});
