import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS, OFFICE_READER_HEADERS, setOfficeAcl } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

async function fixture(page, mime = "image/png") {
  const value = await page.evaluate((type) => {
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 160;
    const context = canvas.getContext("2d"); context.fillStyle = "#2563eb"; context.fillRect(0, 0, 160, 160);
    context.fillStyle = "#f97316"; context.fillRect(160, 0, 160, 160);
    return canvas.toDataURL(type).split(",")[1];
  }, mime);
  return Buffer.from(value, "base64");
}

async function upload(page, id, bytes, mime = "image/png", headers = OFFICE_HEADERS) {
  return page.request.post(`${BASE_URL}/v1/office/documents/${id}/images`, { data: bytes,
    headers: { ...headers, "Content-Type": mime, "X-Office-Upload-Confirmed": "true" } });
}

async function insert(page, bytes, mime = "image/png") {
  await officeEditor(page).press("Control+End");
  await page.locator("#image-options").click();
  await page.locator("#image-file").setInputFiles({ name: mime === "image/png" ? "sample.png" : "sample.jpg", mimeType: mime, buffer: bytes });
  await page.locator("#image-upload").click();
  await expect(page.locator("#image-status")).toContainText("Bild bereit");
  await expect(page.locator("#image-preview img")).toBeVisible();
  await page.locator("#image-alt").fill("Blue and orange squares");
  await page.locator("#image-caption").fill("<literal image caption>");
  await page.locator("#image-apply").click();
  await expect(page.locator("#image-dialog")).toBeHidden();
  await expect(officeEditor(page).locator("img")).toBeVisible();
}

test("Office image upload insert resize undo save reopen and real PDF preserve exact assets", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Image workflow", "Before the image");
  const bytes = await fixture(page); await insert(page, bytes);
  await expect(officeEditor(page).locator("figcaption")).toHaveText("<literal image caption>");
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-width").fill("240"); await expect(page.locator("#image-height")).toHaveValue("120");
  await page.locator("#image-align").selectOption("center"); await page.locator("#image-apply").click();
  await expect(officeEditor(page).locator("img")).toHaveAttribute("width", "240");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("img")).toHaveAttribute("width", "320");
  await officeEditor(page).press("Control+Shift+z"); await expect(officeEditor(page).locator("img")).toHaveAttribute("width", "240");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const attrs = saved.content.content.find((entry) => entry.type === "image").attrs;
  expect(attrs).toMatchObject({ width: 240, height: 120, align: "center", alt: "Blue and orange squares", decorative: false });
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img")).toBeVisible();
  const prints = await installPrintProbe(page, { pdfName: "office-images-output.pdf" });
  await openPrintPreview(page, first.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview img")).toHaveAttribute("alt", attrs.alt);
  await submitOfficePrint(page, first.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1);
  expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Image");
  expect(prints[0].snapshot.text).toContain("<literal image caption>");
});

test("Office image JPEG normalization strips original metadata and decoder rejects malformed and oversized pixels", async ({ page }) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Image validation", "Image bounds");
  const jpeg = await fixture(page, "image/jpeg");
  const response = await upload(page, first.document.object_id, jpeg, "image/jpeg"); expect(response.status()).toBe(200);
  const attrs = (await response.json()).image;
  const read = await page.request.get(`${BASE_URL}/v1/office/documents/${attrs.documentId}/images/${attrs.assetId}/${attrs.versionId}`, { headers: OFFICE_HEADERS });
  expect(read.status()).toBe(200); expect(read.headers()["content-type"]).toBe("image/png"); expect(read.headers()["cache-control"]).toBe("no-store");
  expect((await read.body()).subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  for (const [bytes, mime] of [[Buffer.from("<svg onload='x'/>") , "image/svg+xml"], [jpeg, "image/png"], [jpeg.subarray(0, 30), "image/jpeg"], [Buffer.from([137,80,78,71,13,10,26,10]), "image/png"]]) {
    expect((await upload(page, first.document.object_id, bytes, mime)).status()).toBe(400);
  }
  const png = await fixture(page); png.writeUInt32BE(20000, 16);
  expect((await upload(page, first.document.object_id, png)).status()).toBe(400);
  expect((await upload(page, first.document.object_id, Buffer.alloc(8388609))).status()).toBe(413);
  expect((await officeContent(page, first.document.object_id)).version.version_id).toBe(first.version.version_id);
});

test("Office image reader and forged cross-document references cannot upload or bind someone else's image", async ({ page }) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Image source rights", "Source");
  const bytes = await fixture(page); const response = await upload(page, first.document.object_id, bytes);
  expect(response.status()).toBe(200); const attrs = (await response.json()).image;
  const second = await createOfficeDocument(page, "Image target rights", "Target");
  const save = await page.request.post(`${BASE_URL}/v1/office/documents/${second.document.object_id}/versions`, { headers: OFFICE_HEADERS, data: {
    title: "Wrong image", document: { type: "doc", content: [{ type: "image", attrs }] }, mutation_reference: "wrong-image-reference",
    expected_current_version_id: second.version.version_id, human_confirmation: true,
  } }); expect(save.status()).toBe(400);
  expect((await upload(page, first.document.object_id, bytes, "image/png", OFFICE_READER_HEADERS)).status()).toBe(404);
  const wrong = await page.request.get(`${BASE_URL}/v1/office/documents/${second.document.object_id}/images/${attrs.assetId}/${attrs.versionId}`, { headers: OFFICE_HEADERS });
  expect(wrong.status()).toBe(404);
  const foreign = await page.request.get(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images/${attrs.assetId}/${attrs.versionId}`, { headers: { ...OFFICE_HEADERS, "X-Tenant-Id": "tenant-other" } });
  expect([403, 404]).toContain(foreign.status());
});

test("Office image dialog supports decorative images cancellation removal and keyboard undo", async ({ page }) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Image removal", "Before");
  await insert(page, await fixture(page));
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-decorative").check(); await page.locator("#image-apply").click();
  await expect(officeEditor(page).locator("img")).toHaveAttribute("alt", "");
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-width").fill("99"); await page.keyboard.press("Escape");
  await expect(officeEditor(page).locator("img")).toHaveAttribute("width", "320");
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-remove").click(); await expect(officeEditor(page).locator("img")).toHaveCount(0);
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("img")).toHaveAttribute("alt", "");
  await saveOffice(page, { objectId: first.document.object_id });
});

test("Office image controls fit desktop tablet and mobile", async ({ page }, testInfo) => {
  await openOffice(page); await createOfficeDocument(page, "Image layout", "Visible content"); await insert(page, await fixture(page));
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-preview img")).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-images-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator("#image-apply").scrollIntoViewIfNeeded(); await expect(page.locator("#image-apply")).toBeVisible();
  if (testInfo.project.name.includes("desktop")) {
    await page.setViewportSize({ width: 900, height: 900 }); await page.screenshot({ path: `${ARTIFACT_DIR}/office-images-tablet.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
