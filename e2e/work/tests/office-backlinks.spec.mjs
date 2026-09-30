import { expect, test } from "@playwright/test";

import { createOfficeDocument, officeEditor, openOffice, openOfficeDocument, saveOffice, setOfficeAcl } from "./office-support.mjs";

async function selectText(page, start, end) {
  await officeEditor(page).evaluate((root, [from, to]) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node, offset = 0, first = null, last = null;
    while ((node = walker.nextNode())) {
      const next = offset + node.data.length;
      if (!first && from >= offset && from <= next) first = [node, from - offset];
      if (to >= offset && to <= next) { last = [node, to - offset]; break; }
      offset = next;
    }
    const range = document.createRange(); range.setStart(...first); range.setEnd(...last);
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    root.dispatchEvent(new Event("selectionchange", { bubbles: true }));
  }, [start, end]);
}

test("Office backlinks show only freshly readable current sources and deliberately open the exact version", async ({ page }) => {
  await openOffice(page);
  const target = await createOfficeDocument(page, "Backlink target", "Target body");
  const source = await createOfficeDocument(page, "Backlink source", "Read target version");
  await selectText(page, 5, 11);
  await page.locator("#document-reference-options").click();
  await page.locator("#document-reference-target").selectOption({ label: "Backlink target" });
  await page.locator("#document-reference-apply").click();
  const savedSource = await saveOffice(page, { objectId: source.document.object_id });

  await openOfficeDocument(page, target.document.object_id);
  await page.locator("#document-backlinks").click();
  await expect(page.locator("#backlinks-dialog")).toBeVisible();
  const backlink = page.locator("#backlinks-list .backlink-item");
  await expect(backlink).toHaveCount(1);
  await expect(backlink).toContainText("Backlink source");
  await expect(backlink).toContainText("1 Verweis");
  await backlink.click();
  await expect(page.locator("#document-version")).toContainText(savedSource.version.version_id);
  await expect(officeEditor(page)).toContainText("Read target version");

  await setOfficeAcl(page, source.document.object_id, { status: "revoked", creator: true });
  try {
    await openOfficeDocument(page, target.document.object_id);
    await page.locator("#document-backlinks").click();
    await expect(page.locator("#backlinks-list .backlink-item")).toHaveCount(0);
    await expect(page.locator("#backlinks-status")).toHaveText("Keine aktuell lesbaren Rückverweise auf diese Version.");
    await expect(page.locator("#backlinks-dialog")).not.toContainText("Backlink source");
  } finally {
    await setOfficeAcl(page, source.document.object_id, { status: "active", creator: true });
  }
});
