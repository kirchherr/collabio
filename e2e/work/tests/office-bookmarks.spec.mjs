import { test, expect } from "@playwright/test";
import { createOfficeDocument, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function selectText(page, start, end) {
  await officeEditor(page).evaluate((root, [from, to]) => {
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
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  }, [start, end]);
}

test("Office keeps stable bookmarks and deliberate internal cross-reference navigation through exact versions", async ({ page }) => {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await openOffice(page);
  const first = await createOfficeDocument(page, "Bookmark proof", "Target See target");
  await openOfficeDocument(page, first.document.object_id);
  await selectText(page, 0, 0); await page.locator("#bookmark-options").click();
  await page.locator("#bookmark-label").fill("Overview"); await page.locator("#bookmark-apply").click();
  const marker = officeEditor(page).locator("[data-office-bookmark]");
  await expect(officeEditor(page).locator("[data-office-bookmark]")).toHaveCount(1);
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("[data-office-bookmark]")).toHaveCount(0);
  await officeEditor(page).press("Control+Shift+z"); await expect(officeEditor(page).locator("[data-office-bookmark]")).toHaveCount(1);
  const bookmarkId = await marker.getAttribute("data-office-bookmark");
  await selectText(page, 7, 17); await page.locator("#cross-reference-options").click();
  await expect(page.locator("#cross-reference-target option")).toHaveText(["Overview"]);
  await page.locator("#cross-reference-apply").click();
  await expect(officeEditor(page).locator(`[data-office-cross-reference="${bookmarkId}"]`)).toHaveText("See target");
  await selectText(page, 7, 17); await page.locator("#cross-reference-options").click();
  const beforeJump = requests.length; await page.locator("#cross-reference-jump").click();
  await expect(marker).toHaveClass(/ProseMirror-selectednode/); expect(requests).toHaveLength(beforeJump);
  expect(await page.evaluate(() => location.hash)).toBe("");
  const second = await saveOffice(page, { objectId: first.document.object_id });
  const savedBookmark = second.content.content[0].content.find((entry) => entry.type === "bookmark");
  expect(savedBookmark.attrs.label).toBe("Overview");
  expect(second.content.content[0].content.find((entry) => entry.marks?.some((mark) => mark.type === "crossReference")).marks)
    .toContainEqual({ type: "crossReference", attrs: { targetId: savedBookmark.attrs.id } });
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await marker.click(); await page.locator("#bookmark-options").click();
  await page.locator("#bookmark-label").fill("Executive overview"); await page.locator("#bookmark-apply").click();
  const renamed = await saveOffice(page, { objectId: first.document.object_id });
  expect(renamed.content.content[0].content.find((entry) => entry.type === "bookmark").attrs).toEqual({
    id: savedBookmark.attrs.id, label: "Executive overview",
  });
  await officeEditor(page).locator("[data-office-bookmark]").click(); await page.locator("#bookmark-options").click();
  await page.locator("#bookmark-remove").click();
  await expect(officeEditor(page).locator("[data-office-bookmark]")).toHaveCount(0);
  await selectText(page, 7, 17); await page.locator("#cross-reference-options").click();
  await expect(page.locator("#cross-reference-status")).toContainText("Ziel nicht verfügbar");
  await expect(page.locator("#cross-reference-jump")).toBeDisabled();
  await page.locator("#cross-reference-remove").click();
  await expect(officeEditor(page).locator("[data-office-cross-reference]")).toHaveCount(0);
});
