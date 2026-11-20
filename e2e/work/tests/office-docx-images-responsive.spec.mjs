import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const SOURCE = "work-e2e-stored-docx-images", VERSION = "stored-docx-images-v1";
const imagesOf = (content) => content.content.filter((node) => node.type === "image").map((node) => node.attrs);
async function alphaValues(page) {
  return officeEditor(page).locator(".office-image img").first().evaluate(async (image) => {
    await image.decode();
    const canvas = document.createElement("canvas"); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d"); context.drawImage(image, 0, 0);
    return [0, 100, 250].map((x) => context.getImageData(x, 0, 1, 1).data[3]);
  });
}

test("Office imports embedded DOCX alpha images and owns them only after confirmed save", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  let createRequest = null, creates = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/v1/office/documents" && request.method() === "POST") {
      creates += 1; createRequest = request.postDataJSON();
    }
  });
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  await page.locator("#document-import").click();
  const dialog = page.locator("#import-document-dialog");
  await expect(dialog.locator("#import-source-select")).toContainText("mit Bildern");
  await dialog.locator("#import-source-select").selectOption(`${SOURCE}\u001f${VERSION}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending; expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.content_persisted).toBe(false);
  expect(preview.source_version_id).toBe(VERSION);
  const temporary = imagesOf(preview.document); expect(temporary).toHaveLength(2);
  expect(temporary.map((attrs) => attrs.alt)).toEqual(["Erstes transparentes Quellbild", "Zweites Quellbild"]);
  await expect(officeEditor(page).locator(".office-image img")).toHaveCount(2);
  expect(await alphaValues(page)).toEqual([0, 128, 255]);
  await officeEditor(page).locator(".office-image-edit").first().click();
  await expect(page.locator("#image-dialog")).toBeVisible();
  await expect(page.locator("#image-crop-source")).toHaveJSProperty("naturalWidth", 320);
  await expect(page.locator("#image-duplicate")).toBeDisabled();
  await page.locator("#image-caption").fill("Bild aus der gespeicherten DOCX-Quelle");
  await page.locator("#image-apply").click();
  await expect(page.locator("#image-dialog")).toBeHidden();
  expect(creates).toBe(0);
  // A temporary identity does not authorize any stored asset content.
  const fakePath = `/v1/office/documents/${temporary[0].documentId}/images/${temporary[0].assetId}/${temporary[0].versionId}`;
  expect((await page.request.get(`${BASE_URL}${fakePath}`, { headers: OFFICE_HEADERS })).status()).toBe(404);
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  expect(creates).toBe(0);
  const saved = await saveOffice(page);
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  const persisted = imagesOf(exact.content);
  expect(persisted[0].caption).toBe("Bild aus der gespeicherten DOCX-Quelle");
  expect(persisted).toHaveLength(2);
  expect(saved.document.information_classification).toBe("confidential");
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  for (const [index, attrs] of persisted.entries()) {
    expect(attrs.documentId).toBe(saved.document.object_id);
    expect(attrs.assetId).not.toBe(temporary[index].assetId);
    expect(attrs.contentHash).toBe(temporary[index].contentHash);
    const path = `${BASE_URL}/v1/office/documents/${attrs.documentId}/images/${attrs.assetId}/${attrs.versionId}`;
    const denied = await page.request.get(path, { headers: { ...OFFICE_READER_HEADERS, "X-Readable-Object-Ids": attrs.assetId } });
    expect(denied.status()).toBe(404);
  }
  const replay = await page.request.post(`${BASE_URL}/v1/office/documents`, { headers: OFFICE_HEADERS, data: createRequest });
  expect(replay.status()).toBe(200);
  const replayed = await replay.json(); expect(replayed.replayed).toBe(true);
  expect(imagesOf(replayed.content)).toEqual(persisted);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator(".office-image img")).toHaveCount(2);
  expect(await alphaValues(page)).toEqual([0, 128, 255]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await officeEditor(page).locator(".office-image").first().scrollIntoViewIfNeeded();
  await officeEditor(page).locator(".office-image").first().screenshot({ path: `${ARTIFACT_DIR}/office-docx-alpha-${testInfo.project.name}.png` });
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-images-${testInfo.project.name}.png`, fullPage: true });
});
