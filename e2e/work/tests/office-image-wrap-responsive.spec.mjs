import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint, pdfPageCount } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const body = "Nachfolgender Text bleibt lesbar und fließt am Bild vorbei. Die Reihenfolge des Dokuments bleibt erhalten. ";
async function fixture(page, multipage = false) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Image wrapping", "Wrap introduction");
  const bytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 160;
    const context = canvas.getContext("2d"); context.fillStyle = "#2563eb"; context.fillRect(0, 0, 160, 160);
    context.fillStyle = "#f97316"; context.fillRect(160, 0, 160, 160); return canvas.toDataURL().split(",")[1];
  }), "base64");
  const response = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images`, {
    data: bytes, headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
  }); expect(response.status()).toBe(200);
  const attrs = { ...(await response.json()).image, width: 180, height: 180, alt: "Orange wrapped image", decorative: false,
    caption: "<wrap caption>", crop: { x: 160, y: 0, width: 160, height: 160 } };
  const image = { type: "image", attrs };
  const content = multipage ? [
    ...Array.from({ length: 8 }, (_, index) => paragraph(`Before-wrap-${index + 1}: ${body.repeat(2)}`)),
    { ...image, attrs: { ...attrs, wrap: { side: "left", gap: 24 } } }, paragraph(`LEFT-WRAP ${body.repeat(4)}`),
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "CLEAR-HEADING" }] },
    { ...image, attrs: { ...attrs, wrap: { side: "right", gap: 16 } } }, paragraph(`RIGHT-WRAP ${body.repeat(4)}`),
    ...Array.from({ length: 10 }, (_, index) => paragraph(`After-wrap-${index + 1}: ${body.repeat(2)}`)),
    paragraph("WRAP-END"),
  ] : [paragraph("Wrap introduction"), image, paragraph(`WRAPPED-TEXT ${body.repeat(6)}`),
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "After wrapping" }] }, paragraph("WRAP-END")];
  const saved = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: { type: "doc", content },
      mutation_reference: `wrap-fixture-${first.document.object_id}`, expected_current_version_id: first.version.version_id, human_confirmation: true },
  }); expect(saved.status()).toBe(200);
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img").first()).toBeVisible();
  return { saved: await saved.json(), attrs };
}
async function edit(page) {
  await officeEditor(page).locator("img").first().click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-preview img")).toBeVisible();
}
async function wrap(page, side, gap = 16) {
  await edit(page); await page.locator("#image-wrap").selectOption(side);
  if (side !== "none") await page.locator("#image-wrap-gap").fill(String(gap));
  await page.locator("#image-apply").click();
}
async function layout(page, side) {
  const metrics = await officeEditor(page).evaluate((root) => {
    const image = root.querySelector(".office-image-node"), after = image.nextElementSibling;
    const rect = image.getBoundingClientRect(), range = document.createRange();
    range.setStart(after.firstChild, 0); range.setEnd(after.firstChild, 1);
    const text = range.getBoundingClientRect();
    return { width: root.clientWidth, float: getComputedStyle(image).cssFloat,
      left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      textLeft: text.left, textRight: text.right, textTop: text.top };
  });
  expect(metrics.float).toBe(metrics.width <= 480 ? "none" : side);
  if (metrics.width <= 480) expect(metrics.textTop).toBeGreaterThanOrEqual(metrics.bottom);
  else {
    expect(metrics.textTop).toBeLessThan(metrics.bottom);
    if (side === "left") expect(metrics.textLeft).toBeGreaterThanOrEqual(metrics.right + 15);
    else expect(metrics.textRight).toBeLessThan(metrics.left);
  }
}

test("Office image wrapping applies left right reset undo immutable history and owned copy", async ({ page }, testInfo) => {
  const { saved: baseline, attrs } = await fixture(page), objectId = baseline.document.object_id;
  await wrap(page, "left"); await layout(page, "left");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator(".office-image-node")).not.toHaveAttribute("data-image-wrap");
  await wrap(page, "left"); const left = await saveOffice(page, { objectId });
  expect(left.content.content[1].attrs).toEqual({ ...attrs, wrap: { side: "left", gap: 16 } });
  await wrap(page, "right", 24); await layout(page, "right"); const right = await saveOffice(page, { objectId });
  expect(right.version.previous_version_id).toBe(left.version.version_id);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-wrap-document-${testInfo.project.name}.png`, fullPage: true });
  await wrap(page, "none"); const reset = await saveOffice(page, { objectId });
  expect(reset.content).toEqual(baseline.content); expect(reset.version.previous_version_id).toBe(right.version.version_id);
  expect((await officeContent(page, objectId, { versionId: left.version.version_id })).content).toEqual(left.content);
  await openReuseHistory(page, right); await expect(page.locator("#image-options")).toBeDisabled();
  await openReuse(page, right, "Independent wrapped copy"); await submitReuse(page, right); await expectReuseDraft(page, "Independent wrapped copy");
  const copy = await saveOffice(page), copied = copy.content.content[1].attrs;
  expect(copied.wrap).toEqual({ side: "right", gap: 24 }); expect(copied.crop).toEqual(attrs.crop);
  expect(copied.assetId).not.toBe(attrs.assetId); expect(copied.contentHash).toBe(attrs.contentHash);
});

test("Office image wrapping previews invalid gaps cancel no-op and responsive fallback without rewriting", async ({ page }, testInfo) => {
  const { saved } = await fixture(page); await edit(page);
  await page.locator("#image-wrap").selectOption("left");
  await expect(page.locator("#image-preview .image-layout-sample")).toBeVisible();
  for (const value of ["49", "-1", "0.5", ""]) {
    await page.locator("#image-wrap-gap").fill(value); await page.locator("#image-apply").click();
    await expect(page.locator("#image-dialog")).toBeVisible();
  }
  await page.locator("#image-wrap-gap").fill("48");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-wrap-dialog-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#image-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled();
  await wrap(page, "none"); await expect(page.locator("#document-save")).toBeDisabled();
  await wrap(page, "left"); await saveOffice(page, { objectId: saved.document.object_id });
  for (const width of [1440, 900, 393]) {
    await page.setViewportSize({ width, height: 960 }); await layout(page, "left");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  await page.setViewportSize({ width: 900, height: 960 });
  if (testInfo.project.name.includes("desktop")) await page.screenshot({ path: `${ARTIFACT_DIR}/office-wrap-tablet.png`, fullPage: true });
});

test("Office image wrapping clears structural blocks and prints cropped images across real PDF pages", async ({ page }, testInfo) => {
  const { saved } = await fixture(page, true);
  const prints = await installPrintProbe(page, { pdfName: `office-wrap-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview [data-image-wrap]")).toHaveCount(2);
  const heading = await page.locator("#print-preview h2").boundingBox();
  const first = await page.locator("#print-preview figure").first().boundingBox();
  expect(heading.y).toBeGreaterThanOrEqual(first.y + first.height);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf?.length || 0).toBeGreaterThan(0);
  expect(pdfPageCount(prints[0].pdf, 595, 842)).toBeGreaterThan(1);
  expect(prints[0].snapshot.text).toContain("WRAP-END");
  expect(prints[0].snapshot.html).toContain('data-image-wrap="left"');
  expect(prints[0].snapshot.html).toContain('data-image-wrap="right"');
});
