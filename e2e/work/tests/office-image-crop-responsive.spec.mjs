import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

async function setup(page) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Crop workflow", "Before the cropped image");
  const bytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 160;
    const context = canvas.getContext("2d"); context.fillStyle = "#2563eb"; context.fillRect(0, 0, 160, 160);
    context.fillStyle = "#f97316"; context.fillRect(160, 0, 160, 160); return canvas.toDataURL().split(",")[1];
  }), "base64");
  const uploaded = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images`, {
    data: bytes, headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
  }); expect(uploaded.status()).toBe(200);
  const attrs = { ...(await uploaded.json()).image, alt: "Orange half of the image", decorative: false, caption: "<crop caption>" };
  const response = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: { ...first.content, content: [...first.content.content, { type: "image", attrs }] },
      mutation_reference: `crop-fixture-${first.document.object_id}`, expected_current_version_id: first.version.version_id, human_confirmation: true },
  }); expect(response.status()).toBe(200);
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img")).toBeVisible();
  return { saved: await response.json(), attrs };
}
async function edit(page) {
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-crop-section summary").click();
  await expect(page.locator("#image-crop-source")).toBeVisible();
}
async function orangeCrop(page) {
  await page.locator("#image-crop-width").fill("160"); await page.locator("#image-crop-x").fill("160");
  await page.locator("#image-width").fill("200"); await expect(page.locator("#image-height")).toHaveValue("200");
}

test("Office crop numeric preview undo save history reset copy and actual PDF keep original pixels", async ({ page }, testInfo) => {
  const { saved: first, attrs } = await setup(page);
  await edit(page); await orangeCrop(page);
  await expect(page.locator("#image-preview .office-image-viewport")).toBeVisible();
  await page.locator("#image-apply").click();
  await expect(officeEditor(page).locator(".office-image-viewport")).toHaveCount(1);
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator(".office-image-viewport")).toHaveCount(0);
  await officeEditor(page).press("Control+Shift+z");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const cropped = saved.content.content.find((node) => node.type === "image").attrs;
  expect(cropped).toEqual({ ...attrs, width: 200, height: 200, crop: { x: 160, y: 0, width: 160, height: 160 } });
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator(".office-image-viewport")).toBeVisible();
  const prints = await installPrintProbe(page, { pdfName: `office-crop-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview .office-image-viewport")).toHaveCount(1);
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf?.length || 0).toBeGreaterThan(0);
  await page.locator("#print-close").click();
  await edit(page); await page.locator("#image-crop-reset").click(); await page.locator("#image-apply").click();
  const reset = await saveOffice(page, { objectId: first.document.object_id });
  expect(reset.content.content.find((node) => node.type === "image").attrs.crop).toBeUndefined();
  expect((await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id })).content).toEqual(saved.content);
  await openReuseHistory(page, saved);
  await openReuse(page, saved, "Independent cropped copy"); await submitReuse(page, saved); await expectReuseDraft(page, "Independent cropped copy");
  const copy = await saveOffice(page);
  const copied = copy.content.content.find((node) => node.type === "image").attrs;
  expect(copied.crop).toEqual(cropped.crop); expect(copied.contentHash).toBe(attrs.contentHash); expect(copied.assetId).not.toBe(attrs.assetId);
});

test("Office crop pointer keyboard invalid bounds cancellation and reset stay local", async ({ page }, testInfo) => {
  const { saved } = await setup(page); await edit(page);
  const stage = page.locator("#image-crop-stage"); await stage.scrollIntoViewIfNeeded();
  const box = await stage.boundingBox();
  await page.mouse.move(box.x + box.width / 4, box.y + box.height / 4); await page.mouse.down();
  await page.mouse.move(box.x + box.width * 3 / 4, box.y + box.height * 3 / 4); await page.mouse.up();
  await expect(page.locator("#image-crop-x")).toHaveValue("80"); await expect(page.locator("#image-crop-width")).toHaveValue("160");
  await stage.press("Shift+ArrowRight"); await expect(page.locator("#image-crop-x")).toHaveValue("90");
  await stage.press("ArrowLeft"); await expect(page.locator("#image-crop-x")).toHaveValue("89");
  await page.locator("#image-crop-x").fill("319"); await page.locator("#image-apply").click();
  await expect(page.locator("#image-dialog")).toBeVisible();
  await page.locator("#image-crop-x").fill("80");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-crop-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (testInfo.project.name.includes("desktop")) {
    await page.setViewportSize({ width: 900, height: 900 });
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-crop-tablet.png`, fullPage: true });
  }
  await page.locator("#image-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled();
  expect((await officeContent(page, saved.document.object_id)).version.version_id).toBe(saved.version.version_id);
  await edit(page); await page.locator("#image-lock").uncheck(); await orangeCropUnlocked(page);
  await expect(page.locator("#image-preview img")).toHaveCSS("object-fit", "fill");
  await page.locator("#image-crop-reset").click(); await expect(page.locator("#image-height")).toHaveValue("160");
  await page.locator("#image-lock").check();
  await page.locator("#image-apply").click(); await expect(page.locator("#document-save")).toBeDisabled();
});

async function orangeCropUnlocked(page) {
  await page.locator("#image-crop-width").fill("160"); await page.locator("#image-crop-x").fill("160");
  await expect(page.locator("#image-height")).toHaveValue("160");
}
