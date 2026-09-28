import { test, expect } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

async function selectText(page, start, end) {
  await officeEditor(page).evaluate(async (root, [from, to]) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node, offset = 0, first = null, last = null;
    while ((node = walker.nextNode())) {
      const next = offset + node.data.length;
      if (!first && from >= offset && from <= next) first = [node, from - offset];
      if (to >= offset && to <= next) { last = [node, to - offset]; break; }
      offset = next;
    }
    const range = document.createRange(); range.setStart(...first); range.setEnd(...last);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, [start, end]);
}

test("Office link dialog stays responsive and print keeps one semantic safe annotation", async ({ page }, testInfo) => {
  const externalRequests = [];
  page.on("request", (request) => {
    if (request.url().startsWith("https://example.org/")) externalRequests.push(request.url());
  });
  await openOffice(page);
  const first = await createOfficeDocument(page, "Responsive link proof", "Open reference now");
  await openOfficeDocument(page, first.document.object_id);
  await selectText(page, 5, 14); await page.locator("#link-options").click();
  const dialog = page.locator("#link-dialog"); await expect(dialog).toBeVisible();
  await page.locator("#link-href").fill("https://example.org/docs?q=1#part");
  const box = await dialog.boundingBox(); expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-link-dialog-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#link-apply").click();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const prints = await installPrintProbe(page, { pdfName: `office-links-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const printLink = page.locator('#print-preview a[href="https://example.org/docs?q=1#part"]');
  await expect(printLink).toHaveCount(1); await expect(printLink).toHaveAttribute("rel", "noopener noreferrer");
  await expect(printLink).not.toHaveAttribute("target", /.+/);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1); await expect.poll(() => prints[0].pdf).not.toBeNull();
  expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Link");
  expect(externalRequests).toEqual([]);
});
