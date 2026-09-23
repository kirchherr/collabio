import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe, pdfPageCount } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const marker = { type: "pageBreak" };
const markers = (page) => officeEditor(page).locator(".office-page-break");
async function fixture(page, content) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Page boundary proof", "Initial boundary source");
  return publish(page, first, content);
}
async function publish(page, previous, content) {
  const response = await page.request.post(`${BASE_URL}/v1/office/documents/${previous.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: previous.version.title, document: { type: "doc", content },
      mutation_reference: `page-break-fixture-${previous.version.version_id}`, expected_current_version_id: previous.version.version_id, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  const saved = await response.json(); await page.locator("#document-reload").click();
  await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await expect(page.locator("#document-save")).toBeDisabled();
  return saved;
}
async function selectText(locator, from = 0, to = from) {
  await locator.click();
  await locator.evaluate(async (element, offsets) => {
    element.closest('[contenteditable="true"]').focus();
    // Let the editor's focus restoration finish before selecting the fixture range.
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), text = walker.nextNode();
    if (!text) throw new Error("Missing fixture text");
    const range = document.createRange(); range.setStart(text, offsets.from); range.setEnd(text, offsets.to);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, { from, to });
}

test("Office page breaks split formatted text preserve isolated undo history and independent copies", async ({ page }, testInfo) => {
  const baseline = await fixture(page, [{ type: "heading", attrs: { level: 2, textAlign: "right", spacingAfter: 12 },
    content: [{ type: "text", text: "BeforeAfter", marks: [{ type: "bold" }] }] }]);
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await selectText(editor.locator("h2"), 6);
  await page.keyboard.press("Control+Enter"); await expect(markers(page)).toHaveCount(1);
  await page.keyboard.insertText("X"); await page.keyboard.press("Control+z");
  await expect(editor.locator("h2").last()).toHaveText("After"); await expect(markers(page)).toHaveCount(1);
  await page.keyboard.press("Control+z"); await expect(markers(page)).toHaveCount(0);
  await expect(editor.locator("h2")).toHaveText("BeforeAfter");
  await page.keyboard.press("Control+Shift+z"); await expect(markers(page)).toHaveCount(1);
  const broken = await saveOffice(page, { objectId });
  expect(broken.content.content.map((node) => node.type)).toEqual(["heading", "pageBreak", "heading"]);
  expect(broken.content.content[0].attrs).toEqual(baseline.content.content[0].attrs);
  expect(broken.content.content[2].attrs).toEqual(baseline.content.content[0].attrs);
  expect(broken.content.content[2].content[0].marks).toEqual([{ type: "bold" }]);
  await markers(page).click(); await expect(markers(page)).toHaveClass(/ProseMirror-selectednode/);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-page-break-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#insert-menu").selectOption("removePageBreak"); await expect(markers(page)).toHaveCount(0);
  const removed = await saveOffice(page, { objectId });
  expect(removed.content.content).toEqual(broken.content.content.filter((node) => node.type !== "pageBreak"));
  expect(removed.version.previous_version_id).toBe(broken.version.version_id);
  expect((await officeContent(page, objectId, { versionId: broken.version.version_id })).content).toEqual(broken.content);
  await openReuseHistory(page, broken); await expect(editor).toHaveAttribute("contenteditable", "false");
  await expect(page.locator("#insert-menu")).toBeDisabled();
  await openReuse(page, broken, "Independent page boundaries"); await submitReuse(page, broken);
  await expectReuseDraft(page, "Independent page boundaries");
  const copied = await saveOffice(page); expect(copied.content).toEqual(broken.content);
  expect(copied.document.object_id).not.toBe(objectId);
});

test("Office page breaks support menu and adjacent keyboard removal without deleting surrounding text", async ({ page }) => {
  await fixture(page, [p("Before"), marker, p("After")]);
  const editor = officeEditor(page);
  await selectText(editor.locator("p").last());
  await page.keyboard.press("Backspace"); await expect(markers(page)).toHaveCount(0);
  await expect(editor.locator("p")).toHaveText(["Before", "After"]);
  await page.keyboard.press("Control+z"); await expect(markers(page)).toHaveCount(1);
  await selectText(editor.locator("p").first(), 6);
  await page.keyboard.press("Delete"); await expect(markers(page)).toHaveCount(0);
  await page.keyboard.press("Control+z"); await expect(markers(page)).toHaveCount(1);
  await markers(page).click(); await page.keyboard.press("Delete"); await expect(markers(page)).toHaveCount(0);
  await selectText(editor.locator("p").last());
  await page.locator("#insert-menu").selectOption("pageBreak"); await expect(markers(page)).toHaveCount(1);
  await expect(editor.locator("p").last()).toHaveText("After");
});

test("Office page breaks reject nested contexts text selections and excess markers atomically", async ({ page }) => {
  const nested = [
    { type: "bulletList", content: [{ type: "listItem", content: [p("List text")] }] },
    { type: "blockquote", content: [p("Quote text")] },
    { type: "table", content: [{ type: "tableRow", content: [{ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [p("Cell text")] }] }] },
    { type: "codeBlock", content: [{ type: "text", text: "Code text" }] }, p("Selected text"),
  ];
  const baseline = await fixture(page, nested), editor = officeEditor(page);
  for (const selector of ["li p", "blockquote p", "td p", "pre"]) {
    await selectText(editor.locator(selector));
    await expect(page.locator('#insert-menu option[value="pageBreak"]')).toBeDisabled();
    await page.keyboard.press("Control+Enter");
    await expect(markers(page)).toHaveCount(0); await expect(page.locator("#document-save")).toBeDisabled();
  }
  await selectText(editor.locator(":scope > p"), 0, 13);
  await page.keyboard.press("Control+Enter"); await expect(markers(page)).toHaveCount(0);
  await expect(page.locator("#document-save")).toBeDisabled();
  await publish(page, baseline, [...Array.from({ length: 100 }, () => marker), p("Limit remains intact")]);
  await selectText(editor.locator("p")); await page.keyboard.press("Control+Enter");
  await expect(markers(page)).toHaveCount(100); await expect(page.locator("#document-save")).toBeDisabled();
  await expect(editor.locator("p")).toHaveText("Limit remains intact");
});

for (const paper of ["a4", "letter"]) test(`Office page breaks produce exact ${paper} PDF boundaries around wrapped images headings and tables`, async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  let saved = await fixture(page, [p("PAGE-ONE-BOUNDARY")]);
  const bytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 80; canvas.height = 80;
    const context = canvas.getContext("2d"); context.fillStyle = "#2563eb"; context.fillRect(0, 0, 80, 80);
    return canvas.toDataURL().split(",")[1];
  }), "base64");
  const upload = await page.request.post(`${BASE_URL}/v1/office/documents/${saved.document.object_id}/images`, {
    headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" }, data: bytes,
  }); expect(upload.status()).toBe(200);
  const image = { type: "image", attrs: { ...(await upload.json()).image, width: 160, height: 160, alt: "Blue boundary image",
    decorative: false, caption: "PAGE-ONE-IMAGE", wrap: { side: "left", gap: 16 }, align: "left" } };
  saved = await publish(page, saved, [...(paper === "letter" ? [marker, marker] : []), p("PAGE-ONE-BOUNDARY"), image, p("Text beside the image."), marker,
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "PAGE-TWO-HEADING" }] },
    { type: "table", content: [{ type: "tableRow", content: [{ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [p("PAGE-TWO-TABLE")] }] }] },
    marker, marker, p("PAGE-THREE-END"), marker]);
  const expectedMarkers = paper === "a4" ? 4 : 6;
  await officeEditor(page).locator("img").click();
  await expect(officeEditor(page).locator(".office-image-node")).toHaveClass(/ProseMirror-selectednode/);
  await page.keyboard.press("Control+Enter"); await expect(markers(page)).toHaveCount(expectedMarkers + 1);
  await expect(officeEditor(page).locator(".office-image-node + .office-page-break")).toHaveCount(1);
  await page.keyboard.press("Control+z"); await expect(markers(page)).toHaveCount(expectedMarkers);
  await expect(page.locator("#document-save")).toBeDisabled();
  const prints = await installPrintProbe(page, { pdfName: `office-page-break-${paper}-${testInfo.project.name}.pdf` });
  const readForPrint = async (button) => {
    // Observe both real authorized reads without routing/intercepting them. The
    // final image request must reach the server before PDF generation is tested.
    const contentRead = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/v1/office/documents/${saved.document.object_id}/content` &&
        url.searchParams.get("version_id") === saved.version.version_id;
    });
    const imageRead = page.waitForResponse((response) => new URL(response.url()).pathname ===
      `/v1/office/documents/${saved.document.object_id}/images/${image.attrs.assetId}/${image.attrs.versionId}`);
    await page.locator(button).click();
    for (const response of await Promise.all([contentRead, imageRead])) {
      expect(response.status()).toBe(200); expect(response.headers()["cache-control"]).toContain("no-store");
    }
  };
  await readForPrint("#document-print");
  await expect(page.locator("#print-submit")).toBeEnabled();
  await expect(page.locator("#print-version")).toContainText(saved.version.version_id);
  await page.locator("#print-paper").selectOption(paper);
  await expect(page.locator("#print-preview .office-page-break")).toHaveCount(paper === "a4" ? 4 : 6);
  await readForPrint("#print-submit");
  await expect.poll(() => prints[0]?.pdf?.length || 0, { timeout: 20_000 }).toBeGreaterThan(0);
  expect(pdfPageCount(prints[0].pdf, paper === "a4" ? 595 : 612, paper === "a4" ? 842 : 792)).toBe(paper === "a4" ? 3 : 4);
  expect(prints[0].snapshot.text).toContain("PAGE-THREE-END");
});
