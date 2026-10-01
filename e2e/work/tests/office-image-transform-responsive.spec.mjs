import { test, expect } from "@playwright/test";
import { BASE_URL } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe } from "./office-print-support.mjs";

async function fixture(page) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Image transform recovery", "Transform introduction");
  const bytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 240; canvas.height = 120;
    const context = canvas.getContext("2d"); context.fillStyle = "#0f766e"; context.fillRect(0, 0, 240, 120);
    context.fillStyle = "#f8fafc"; context.font = "bold 30px sans-serif"; context.fillText("TURN", 70, 72);
    return canvas.toDataURL().split(",")[1];
  }), "base64");
  const upload = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images`, {
    data: bytes, headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
  });
  expect(upload.status()).toBe(200);
  const attrs = { ...(await upload.json()).image, width: 180, height: 90, alt: "Transform sample image", decorative: false, caption: "Transform sample" };
  const content = { type: "doc", content: [{ type: "image", attrs }, { type: "paragraph", content: [{ type: "text", text: "Text after transformed image." }] }] };
  const saved = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: content,
      mutation_reference: `transform-fixture-${first.document.object_id}`, expected_current_version_id: first.version.version_id, human_confirmation: true },
  });
  expect(saved.status()).toBe(200); await page.locator("#document-reload").click();
  return { saved: await saved.json(), attrs };
}

test("Office images rotate mirror undo print and reset with responsive geometry", async ({ page }) => {
  const { saved, attrs } = await fixture(page), editor = officeEditor(page), node = editor.locator(":scope > .office-image-node").first();
  await node.click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-rotation")).toHaveValue("0");
  await page.locator("#image-rotation").selectOption("90"); await page.locator("#image-flip-x").check();
  const preview = page.locator("#image-preview .office-image-transform");
  await expect(preview).toHaveAttribute("data-image-rotation", "90"); await expect(preview).toHaveAttribute("data-image-flip-x", "true");
  await page.locator("#image-apply").click();
  const frame = node.locator(".office-image-transform"), stage = node.locator(".office-image-transform-stage");
  await expect(frame).toHaveAttribute("data-image-rotation", "90"); await expect(stage).toHaveCSS("transform", /matrix/);
  const geometry = await frame.evaluate((element) => { const rect = element.getBoundingClientRect(); return { width: rect.width, height: rect.height }; });
  expect(geometry.height).toBeGreaterThan(geometry.width);
  await editor.press("Control+z"); await expect(node.locator(".office-image-transform")).toHaveCount(0);
  await editor.press("Control+Shift+z"); await expect(frame).toHaveAttribute("data-image-rotation", "90");
  const rotated = await saveOffice(page, { objectId: saved.document.object_id });
  expect(rotated.content.content[0].attrs).toEqual({ ...attrs, transform: { rotation: 90, flipX: true, flipY: false } });
  expect((await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id })).content).toEqual(saved.content);

  const prints = await installPrintProbe(page); await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-image-transform[data-image-rotation='90']")).toHaveCount(1);
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1);
  expect(prints[0].snapshot.html).toContain('data-image-flip-x="true"'); await page.locator("#print-close").click();

  await node.click(); await page.locator("#image-options").click(); await page.locator("#image-rotation").selectOption("270");
  await page.locator("#image-flip-y").check(); await page.locator("#image-apply").click();
  const mirrored = await saveOffice(page, { objectId: saved.document.object_id });
  expect(mirrored.content.content[0].attrs.transform).toEqual({ rotation: 270, flipX: true, flipY: true });
  await node.click(); await page.locator("#image-options").click(); await page.locator("#image-rotation").selectOption("0");
  await page.locator("#image-flip-x").uncheck(); await page.locator("#image-flip-y").uncheck(); await page.locator("#image-apply").click();
  const reset = await saveOffice(page, { objectId: saved.document.object_id }); expect(reset.content.content[0].attrs).toEqual(attrs);
});
