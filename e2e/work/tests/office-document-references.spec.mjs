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

function markedText(content) {
  let result = null;
  const walk = (value) => {
    if (value?.type === "text" && value.marks?.some((mark) => mark.type === "documentReference")) result = value;
    for (const child of value?.content || []) walk(child);
  };
  walk(content); return result;
}

test("Office pins an exact cross-document version and hides it after fresh target ACL revocation", async ({ page }) => {
  await openOffice(page);
  const target = await createOfficeDocument(page, "Reference target v1", "Target body v1");
  const source = await createOfficeDocument(page, "Reference source", "Read target version");
  await selectText(page, 5, 11);
  await page.locator("#document-reference-options").click();
  await expect(page.locator("#document-reference-dialog")).toBeVisible();
  await page.locator("#document-reference-target").selectOption({ label: "Reference target v1" });
  await page.locator("#document-reference-apply").click();
  await expect(officeEditor(page).locator("[data-office-document-reference]")).toHaveCount(1);
  const savedSource = await saveOffice(page, { objectId: source.document.object_id });
  const marked = markedText(savedSource.content), reference = marked.marks.find((mark) => mark.type === "documentReference");
  expect(marked.text).toBe("target");
  expect(reference.attrs).toEqual({ targetObjectId: target.document.object_id, targetVersionId: target.version.version_id });

  await openOfficeDocument(page, target.document.object_id);
  await page.locator("#document-title").fill("Reference target v2");
  await officeEditor(page).fill("Target body v2");
  await saveOffice(page, { objectId: target.document.object_id });
  await openOfficeDocument(page, source.document.object_id);
  await expect(officeEditor(page).locator("[data-office-document-reference]")).toHaveAttribute("title", "Reference target v1 · gespeicherte Version");
  await selectText(page, 5, 11); await page.locator("#document-reference-options").click();
  await expect(page.locator("#document-reference-status")).toContainText("Reference target v1 · gespeicherte Version");
  await page.locator("#document-reference-open").click();
  await expect(page.locator("#document-version")).toContainText(target.version.version_id);
  await expect(officeEditor(page)).toHaveText("Target body v1");

  await setOfficeAcl(page, target.document.object_id, { status: "revoked", creator: true });
  try {
    await openOfficeDocument(page, source.document.object_id);
    await expect(officeEditor(page).locator("[data-office-document-reference]")).toHaveAttribute("title", "Dokumentziel nicht verfügbar");
    await selectText(page, 5, 11); await page.locator("#document-reference-options").click();
    await expect(page.locator("#document-reference-status")).toHaveText("Dokumentziel nicht verfügbar");
    await expect(page.locator("#document-reference-open")).toBeDisabled();
    await expect(page.locator("#document-reference-dialog")).not.toContainText("Reference target v1");
    await page.locator("#document-reference-cancel").click();
    await page.locator("#document-print").click();
    await expect(page.locator("#print-preview .office-print-document-reference")).toHaveAttribute("data-office-reference-status", "unavailable");
    await expect(page.locator("#print-preview a[href]")).toHaveCount(0);
    await expect(page.locator("#print-preview")).not.toContainText("Reference target v1");
  } finally {
    await setOfficeAcl(page, target.document.object_id, { status: "active", creator: true });
  }
});
