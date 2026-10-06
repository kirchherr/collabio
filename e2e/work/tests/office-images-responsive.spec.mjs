import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS, OFFICE_READER_HEADERS, setOfficeAcl, showDocumentList } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft } from "./office-reuse-support.mjs";

async function fixture(page, mime = "image/png", width = 320, height = 160) {
  const value = await page.evaluate(({ type, width, height }) => {
    const canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
    const context = canvas.getContext("2d"); context.fillStyle = "#2563eb"; context.fillRect(0, 0, Math.ceil(width / 2), height);
    context.fillStyle = "#f97316"; context.fillRect(Math.ceil(width / 2), 0, Math.floor(width / 2), height);
    return canvas.toDataURL(type).split(",")[1];
  }, { type: mime, width, height });
  return Buffer.from(value, "base64");
}

async function upload(page, id, bytes, mime = "image/png", headers = OFFICE_HEADERS) {
  return page.request.post(`${BASE_URL}/v1/office/documents/${id}/images`, { data: bytes,
    headers: { ...headers, "Content-Type": mime, "X-Office-Upload-Confirmed": "true" } });
}

async function alphaAt(page, bytes, x, y) {
  return page.evaluate(async ({ encoded, x, y }) => {
    const response = await fetch(`data:image/png;base64,${encoded}`);
    const bitmap = await createImageBitmap(await response.blob());
    const canvas = document.createElement("canvas"); canvas.width = bitmap.width; canvas.height = bitmap.height;
    const context = canvas.getContext("2d"); context.drawImage(bitmap, 0, 0);
    return { width: bitmap.width, height: bitmap.height, rgba: [...context.getImageData(x, y, 1, 1).data] };
  }, { encoded: bytes.toString("base64"), x, y });
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

test("Office image upload insert resize undo save reopen and real PDF preserve exact assets", async ({ page }, testInfo) => {
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
  const prints = await installPrintProbe(page, { pdfName: `office-images-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, first.document.object_id, saved.version.version_id);
  await expect(page.locator("#print-preview img")).toHaveAttribute("alt", attrs.alt);
  await submitOfficePrint(page, first.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length, { timeout: 20_000 }).toBe(1);
  await expect.poll(() => prints[0]?.pdf?.length || 0, { timeout: 20_000 }).toBeGreaterThan(0);
  expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Image");
  expect(prints[0].snapshot.text).toContain("<literal image caption>");
});

test("Office image copy owns new assets after source revocation and print rechecks current access", async ({ page }) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Image copy source", "Source image");
  await insert(page, await fixture(page));
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const source = saved.content.content.find((entry) => entry.type === "image").attrs;
  await openReuse(page, saved, "Independent image copy"); await submitReuse(page, saved);
  await expectReuseDraft(page, "Independent image copy"); await expect(officeEditor(page).locator("img")).toBeVisible();
  const copied = await saveOffice(page);
  const own = copied.content.content.find((entry) => entry.type === "image").attrs;
  expect(own.documentId).toBe(copied.document.object_id); expect(own.assetId).not.toBe(source.assetId);
  expect(own.contentHash).toBe(source.contentHash);
  try {
    await setOfficeAcl(page, first.document.object_id, { creator: true, status: "revoked" });
    await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img")).toBeVisible();
    expect((await page.request.get(`${BASE_URL}/v1/office/documents/${source.documentId}/images/${source.assetId}/${source.versionId}`, { headers: OFFICE_HEADERS })).status()).toBe(404);
    const prints = await installPrintProbe(page);
    await openPrintPreview(page, copied.document.object_id, copied.version.version_id);
    await page.route((url) => url.pathname.endsWith(`/images/${own.assetId}/${own.versionId}`), async (route) => {
      await setOfficeAcl(page, copied.document.object_id, { creator: true, status: "revoked" });
      await route.continue();
    }, { times: 1 });
    // The document read succeeds; revocation occurs before the separate asset read.
    await submitOfficePrint(page, copied.document.object_id, copied.version.version_id);
    await expect(page.locator("#print-dialog")).toBeHidden(); expect(prints).toHaveLength(0);
  } finally {
    await setOfficeAcl(page, first.document.object_id, { creator: true });
    await setOfficeAcl(page, copied.document.object_id, { creator: true });
  }
});

test("Office image placement moves whole nodes without changing text and supports keyboard selection", async ({ page }) => {
  await openOffice(page); await createOfficeDocument(page, "Image positioning", "Unchanged paragraph");
  await insert(page, await fixture(page));
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-up").click();
  await expect(officeEditor(page).locator(":scope > div").first()).toHaveClass(/office-image-node/);
  await expect(officeEditor(page).locator("p").first()).toHaveText("Unchanged paragraph");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page).locator(":scope > p").first()).toHaveText("Unchanged paragraph");
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("ArrowLeft");
  await expect(page.locator("#image-options")).toBeEnabled();
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-lock").uncheck(); await page.locator("#image-width").fill("160");
  await page.locator("#image-height").fill("160"); await page.locator("#image-apply").click();
  await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "160");
  const box = await officeEditor(page).locator("img").boundingBox(); expect(box.width).toBeCloseTo(box.height, 0);
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

test("Office imports safe SVG and EPS through the image dialog with transparent canonical renditions", async ({ page }, testInfo) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Vector image import", "Transparent vectors");
  const svg = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="100" height="100" fill="#2563eb" opacity=".5"/></svg>`);
  const eps = Buffer.from(`%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 200 100\n%%EndComments\n0.949 0.451 0.055 setrgbcolor\n0 0 100 100 rectfill\nshowpage\n%%EOF\n`);

  const svgUpload = await upload(page, first.document.object_id, svg, "image/svg+xml"); expect(svgUpload.status()).toBe(200);
  const svgAttrs = (await svgUpload.json()).image;
  const svgRead = await page.request.get(`${BASE_URL}/v1/office/documents/${svgAttrs.documentId}/images/${svgAttrs.assetId}/${svgAttrs.versionId}`, { headers: OFFICE_HEADERS });
  expect(svgRead.status()).toBe(200); expect(svgRead.headers()["content-type"]).toBe("image/png");
  const svgPixels = await alphaAt(page, await svgRead.body(), 1200, 400);
  expect(svgPixels).toMatchObject({ width: 1600, height: 800 }); expect(svgPixels.rgba[3]).toBe(0);
  const svgPaint = await alphaAt(page, await svgRead.body(), 400, 400); expect(svgPaint.rgba[3]).toBeGreaterThanOrEqual(126); expect(svgPaint.rgba[3]).toBeLessThanOrEqual(129);

  const epsUpload = await upload(page, first.document.object_id, eps, "application/postscript"); expect(epsUpload.status()).toBe(200);
  const epsAttrs = (await epsUpload.json()).image;
  const epsRead = await page.request.get(`${BASE_URL}/v1/office/documents/${epsAttrs.documentId}/images/${epsAttrs.assetId}/${epsAttrs.versionId}`, { headers: OFFICE_HEADERS });
  expect(epsRead.status()).toBe(200); expect(epsRead.headers()["content-type"]).toBe("image/png");
  const epsBytes = await epsRead.body(); const epsClear = await alphaAt(page, epsBytes, 1200, 400);
  expect(epsClear).toMatchObject({ width: 1600, height: 800 }); expect(epsClear.rgba[3]).toBe(0);
  const epsPaint = await alphaAt(page, epsBytes, 400, 400); expect(epsPaint.rgba[3]).toBe(255);

  for (const [name, mimeType, buffer, alt] of [["transparent.svg", "image/svg+xml", svg, "Semitransparent blue vector"], ["transparent.eps", "application/postscript", eps, "Orange EPS vector"]]) {
    await officeEditor(page).press("Control+End"); await page.locator("#image-options").click();
    await page.locator("#image-file").setInputFiles({ name, mimeType, buffer }); await page.locator("#image-upload").click();
    await expect(page.locator("#image-status")).toContainText("Bild bereit"); await page.locator("#image-alt").fill(alt);
    await page.locator("#image-apply").click(); await expect(page.locator("#image-dialog")).toBeHidden();
  }
  await expect(officeEditor(page).locator("img")).toHaveCount(2);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content.filter((entry) => entry.type === "image")).toHaveLength(2);
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img")).toHaveCount(2);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-vector-import-${testInfo.project.name}.png`, fullPage: true });
});

test("Office image reader and forged cross-document references cannot upload or bind someone else's image", async ({ page }) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Image source rights", "Source");
  const bytes = await fixture(page); const response = await upload(page, first.document.object_id, bytes);
  expect(response.status()).toBe(200); const attrs = (await response.json()).image;
  await showDocumentList(page);
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

test("Office duplicates one positioned numbered image with independent ownership and isolated undo", async ({ page }, testInfo) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Independent image duplicate", "Before");
  await insert(page, await fixture(page));
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-numbered").check();
  await page.locator("#image-position-layer").selectOption("front");
  await page.locator("#image-position-x").fill("980"); await page.locator("#image-position-y").fill("1190");
  await page.locator("#image-apply").click();
  await officeEditor(page).locator("img").first().click(); await page.locator("#image-options").click();
  await page.route("**/v1/office/documents/*/images/duplicate", async (route) => route.abort(), { times: 1 });
  await page.locator("#image-duplicate").click();
  await expect(page.locator("#image-status")).toContainText("Entwurf wurde nicht geändert");
  await expect(officeEditor(page).locator("img")).toHaveCount(1);
  await page.locator("#image-duplicate").click();
  await expect(officeEditor(page).locator("img")).toHaveCount(2);
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("img")).toHaveCount(1);
  await officeEditor(page).press("Control+Shift+z"); await expect(officeEditor(page).locator("img")).toHaveCount(2);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const images = saved.content.content.filter((entry) => entry.type === "image").map((entry) => entry.attrs);
  expect(images).toHaveLength(2);
  expect(images[1]).toMatchObject({ contentHash: images[0].contentHash, position: { layer: "front", x: 940, y: 1166 } });
  expect(images[1].assetId).not.toBe(images[0].assetId); expect(images[1].versionId).not.toBe(images[0].versionId);
  expect(images[1].figureId).not.toBe(images[0].figureId);
  const copied = await page.request.get(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images/${images[1].assetId}/${images[1].versionId}`, { headers: OFFICE_HEADERS });
  expect(copied.status()).toBe(200); expect((await copied.body()).length).toBeGreaterThan(0);
  await officeEditor(page).locator("img").last().click({ force: true }); await page.locator("#image-options").click();
  await expect(page.locator("#image-duplicate")).toBeEnabled(); await expect(page.locator("#image-preview img")).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-image-duplicate-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#image-cancel").click();
});

test("Office replaces image pixels while preserving presentation with cancel undo redo and persistence", async ({ page }, testInfo) => {
  await openOffice(page); const first = await createOfficeDocument(page, "Replace image file", "Before");
  await insert(page, await fixture(page));
  await officeEditor(page).locator("img").click(); await page.locator("#image-options").click();
  await page.locator("#image-width").fill("300");
  await page.locator("#image-numbered").check();
  await page.locator("#image-position-layer").selectOption("front");
  await page.locator("#image-position-x").fill("640"); await page.locator("#image-position-y").fill("120");
  await page.locator("#image-rotation").selectOption("90"); await page.locator("#image-flip-x").check();
  await page.locator("#image-apply").click();
  const baseline = await saveOffice(page, { objectId: first.document.object_id });
  const original = baseline.content.content.find((entry) => entry.type === "image").attrs;
  const replacement = await fixture(page, "image/png", 200, 300);

  await officeEditor(page).locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-file-label")).toHaveText("Neue Bilddatei");
  await expect(page.locator("#image-upload")).toHaveText("Neue Bilddatei hochladen und prüfen");
  await page.locator("#image-file").setInputFiles({ name: "portrait.png", mimeType: "image/png", buffer: replacement });
  await page.locator("#image-upload").click(); await expect(page.locator("#image-status")).toContainText("Neue Bilddatei bereit");
  await expect(page.locator("#image-width")).toHaveValue("300"); await expect(page.locator("#image-height")).toHaveValue("450");
  await expect(page.locator("#image-alt")).toHaveValue("Blue and orange squares");
  await expect(page.locator("#image-caption")).toHaveValue("<literal image caption>");
  await expect(page.locator("#image-numbered")).toBeChecked(); await expect(page.locator("#image-flip-x")).toBeChecked();
  await page.locator("#image-cancel").click();
  await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "150");

  await officeEditor(page).locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await page.locator("#image-file").setInputFiles({ name: "portrait.png", mimeType: "image/png", buffer: replacement });
  await page.locator("#image-upload").click(); await expect(page.locator("#image-status")).toContainText("Neue Bilddatei bereit");
  await page.locator("#image-apply").click(); await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "450");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "150");
  await officeEditor(page).press("Control+Shift+z"); await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "450");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const changed = saved.content.content.find((entry) => entry.type === "image").attrs;
  expect(changed).toMatchObject({ pixelWidth: 200, pixelHeight: 300, width: 300, height: 450,
    align: original.align, alt: original.alt, caption: original.caption, decorative: original.decorative,
    lockAspect: original.lockAspect, position: original.position, transform: original.transform, figureId: original.figureId });
  expect(changed.assetId).not.toBe(original.assetId); expect(changed.versionId).not.toBe(original.versionId);
  const bytes = await page.request.get(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images/${changed.assetId}/${changed.versionId}`, { headers: OFFICE_HEADERS });
  expect(bytes.status()).toBe(200); expect((await bytes.body()).length).toBeGreaterThan(0);
  await page.locator("#document-reload").click(); await expect(officeEditor(page).locator("img")).toHaveAttribute("height", "450");
  await officeEditor(page).locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-preview img")).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-image-replacement-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#image-cancel").click();
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
