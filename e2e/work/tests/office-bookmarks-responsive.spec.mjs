import { test, expect } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

async function selectText(page, start, end) {
  await officeEditor(page).evaluate(async (root, [from, to]) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (entry) => entry.parentElement?.closest("[data-office-bookmark]") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    let entry, offset = 0, first = null, last = null;
    while ((entry = walker.nextNode())) {
      const next = offset + entry.data.length;
      if (!first && from >= offset && from <= next) first = [entry, from - offset];
      if (to >= offset && to <= next) { last = [entry, to - offset]; break; }
      offset = next;
    }
    const range = document.createRange(); range.setStart(...first); range.setEnd(...last);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, [start, end]);
}

test("Office bookmark dialogs stay responsive and print emits only resolved document-local anchors", async ({ page }, testInfo) => {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await openOffice(page);
  const first = await createOfficeDocument(page, "Responsive bookmark proof", "Target See target");
  await openOfficeDocument(page, first.document.object_id);
  await selectText(page, 0, 0); await page.locator("#bookmark-options").click();
  const dialog = page.locator("#bookmark-dialog"); await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox(); expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-bookmark-dialog-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#bookmark-label").fill("Overview"); await page.locator("#bookmark-apply").click();
  await selectText(page, 7, 17); await page.locator("#cross-reference-options").click();
  await expect(page.locator("#cross-reference-dialog")).toBeVisible(); await page.locator("#cross-reference-apply").click();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const prints = await installPrintProbe(page, { pdfName: `office-bookmarks-${testInfo.project.name}.pdf` });
  const beforePrint = requests.length;
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const target = page.locator('#print-preview [id^="office-bookmark-"]');
  const reference = page.locator('#print-preview a[data-office-cross-reference]');
  await expect(target).toHaveCount(1); await expect(reference).toHaveCount(1);
  await expect(reference).toHaveAttribute("href", `#${await target.getAttribute("id")}`);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1); await expect.poll(() => prints[0].pdf).not.toBeNull();
  expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Link");
  expect(requests.slice(beforePrint).every((url) => url.startsWith(page.url().split("/office")[0]))).toBe(true);
});
