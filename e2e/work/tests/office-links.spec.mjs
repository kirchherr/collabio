import { test, expect } from "@playwright/test";
import { createOfficeDocument, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

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

async function pasteText(page, text) {
  await officeEditor(page).evaluate((root, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    root.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office applies edits removes and explicitly opens a safe link through exact saved versions", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Link proof", "Open reference now");
  await openOfficeDocument(page, first.document.object_id);
  await selectText(page, 5, 14);
  await page.locator("#link-options").click();
  await page.locator("#link-href").fill("https://example.org/docs");
  await page.locator("#link-apply").click();
  await expect(officeEditor(page).locator("a[data-office-link]")).toHaveAttribute("href", "https://example.org/docs");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page).locator("a")).toHaveCount(0);
  await officeEditor(page).press("Control+Shift+z");
  await selectText(page, 5, 14); await page.locator("#link-options").click();
  await page.evaluate(() => { window.openedOfficeLink = null; window.open = (href, target, features) => {
    window.openedOfficeLink = { href, target, features }; return null;
  }; });
  await page.locator("#link-open").click();
  expect(await page.evaluate(() => window.openedOfficeLink)).toEqual({
    href: "https://example.org/docs", target: "_blank", features: "noopener,noreferrer",
  });
  await page.locator("#link-cancel").click();
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(second.content.content[0].content[1].marks).toEqual([{ type: "link", attrs: { href: "https://example.org/docs" } }]);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await selectText(page, 5, 14); await page.locator("#link-options").click();
  await page.locator("#link-href").fill("javascript:alert(1)"); await page.locator("#link-apply").click();
  await expect(page.locator("#link-status")).toContainText("Nur vollständige HTTPS");
  await page.locator("#link-href").fill("mailto:name@example.org"); await page.locator("#link-apply").click();
  const third = await saveOffice(page, { objectId: first.document.object_id });
  expect(third.content.content[0].content[1].marks[0].attrs.href).toBe("mailto:name@example.org");
  await selectText(page, 5, 14); await page.locator("#link-options").click(); await page.locator("#link-remove").click();
  await expect(officeEditor(page)).toHaveText("Open reference now"); await expect(officeEditor(page).locator("a")).toHaveCount(0);
});

test("Office recognizes safe typed and pasted links without opening or rewriting literal text", async ({ page }) => {
  const externalRequests = [];
  page.on("request", (request) => { if (request.url().startsWith("https://example.org/")) externalRequests.push(request.url()); });
  await openOffice(page);
  const first = await createOfficeDocument(page, "Automatic link proof", "Start");
  await openOfficeDocument(page, first.document.object_id);
  await officeEditor(page).locator("p").click(); await page.keyboard.press("End");
  await page.keyboard.type(" https://example.org/typed. ");
  await expect(officeEditor(page).locator('a[href="https://example.org/typed"]')).toHaveText("https://example.org/typed");
  await pasteText(page, "Mail name@example.org! Unsafe http://unsafe.invalid and javascript:alert(1). ");
  await expect(officeEditor(page).locator('a[href="mailto:name@example.org"]')).toHaveText("name@example.org");
  await expect(officeEditor(page).locator("a")).toHaveCount(2);
  await expect(officeEditor(page)).toContainText("Unsafe http://unsafe.invalid and javascript:alert(1).");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("a")).toHaveCount(1);
  await officeEditor(page).press("Control+Shift+z"); await expect(officeEditor(page).locator("a")).toHaveCount(2);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  const savedText = JSON.stringify(second.content);
  expect(savedText).toContain('"href":"https://example.org/typed"');
  expect(savedText).toContain('"href":"mailto:name@example.org"');
  expect(savedText).toContain("http://unsafe.invalid");
  expect(savedText).not.toContain('"href":"http://unsafe.invalid"');
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await openOfficeDocument(page, first.document.object_id);
  await expect(officeEditor(page).locator("a")).toHaveCount(2);
  expect(externalRequests).toEqual([]);
});
