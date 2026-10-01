import { test, expect } from "@playwright/test";
import { BASE_URL } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe } from "./office-print-support.mjs";

const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });

async function fixture(page) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Free image positioning", "Position introduction");
  const bytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 240; canvas.height = 120;
    const context = canvas.getContext("2d"); context.fillStyle = "#0f766e"; context.fillRect(0, 0, 240, 120);
    context.fillStyle = "#f8fafc"; context.font = "bold 32px sans-serif"; context.fillText("LAYER", 56, 72);
    return canvas.toDataURL().split(",")[1];
  }), "base64");
  const upload = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images`, {
    data: bytes, headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
  });
  expect(upload.status()).toBe(200);
  const attrs = { ...(await upload.json()).image, width: 180, height: 90, alt: "Layered sample image", decorative: false, caption: "Layer sample" };
  const content = { type: "doc", content: [
    paragraph("Text above the anchored images."),
    { type: "image", attrs: { ...attrs, position: { layer: "front", x: 120, y: 34 } } },
    paragraph("FRONT-TEXT remains in document order and may be covered by the foreground image."),
    { type: "image", attrs: { ...attrs, position: { layer: "behind", x: 880, y: -24 } } },
    paragraph("BEHIND-TEXT remains selectable above the background image."),
  ] };
  const saved = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: content,
      mutation_reference: `position-fixture-${first.document.object_id}`, expected_current_version_id: first.version.version_id, human_confirmation: true },
  });
  expect(saved.status()).toBe(200);
  await page.locator("#document-reload").click();
  expect(await page.locator("html").getAttribute("data-office-editor-error")).toBeNull();
  expect(await page.locator("html").getAttribute("data-office-open-error")).toBeNull();
  await expect(officeEditor(page).locator(".office-image-anchor")).toHaveCount(2);
  return { saved: await saved.json(), attrs };
}

test("Office images support foreground background and bounded free anchored placement", async ({ page }) => {
  const { saved, attrs } = await fixture(page), editor = officeEditor(page);
  const nodes = editor.locator(":scope > .office-image-node");
  await expect(nodes.nth(0)).toHaveAttribute("data-image-position", "front");
  await expect(nodes.nth(1)).toHaveAttribute("data-image-position", "behind");
  await expect(nodes.nth(0).locator(".office-image-anchor")).toContainText("vor Text");
  await expect(nodes.nth(1).locator(".office-image-anchor")).toContainText("hinter Text");
  const layout = await editor.evaluate((root) => [...root.querySelectorAll(":scope > .office-image-node")].map((node) => {
    const figure = node.querySelector("figure"), rootRect = root.getBoundingClientRect(), rect = figure.getBoundingClientRect();
    return { layer: node.dataset.imagePosition, left: rect.left - rootRect.left, right: rect.right - rootRect.left,
      rootWidth: rootRect.width, z: getComputedStyle(node).zIndex, pointer: getComputedStyle(figure).pointerEvents };
  }));
  expect(layout[0].left).toBeGreaterThanOrEqual(-1); expect(layout[0].right).toBeLessThanOrEqual(layout[0].rootWidth + 1);
  expect(layout[1].left).toBeGreaterThanOrEqual(-1); expect(layout[1].right).toBeLessThanOrEqual(layout[1].rootWidth + 1);
  expect(Number(layout[0].z)).toBeGreaterThan(Number(layout[1].z)); expect(layout[1].pointer).toBe("none");

  await nodes.nth(0).locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await expect(page.locator("#image-position-layer")).toHaveValue("front");
  await expect(page.locator("#image-wrap")).toBeDisabled();
  await page.locator("#image-position-layer").selectOption("behind");
  await page.locator("#image-position-x").fill("700"); await page.locator("#image-position-y").fill("80");
  await page.locator("#image-apply").click();
  await expect(nodes.nth(0)).toHaveAttribute("data-image-position", "behind");
  await editor.press("Control+z"); await expect(nodes.nth(0)).toHaveAttribute("data-image-position", "front");

  await nodes.nth(0).locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await page.locator("#image-position-layer").selectOption("behind");
  await page.locator("#image-position-x").fill("700"); await page.locator("#image-position-y").fill("80");
  await page.locator("#image-apply").click();
  const changed = await saveOffice(page, { objectId: saved.document.object_id });
  expect(changed.content.content[1].attrs).toEqual({ ...attrs, position: { layer: "behind", x: 700, y: 80 } });
  expect((await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id })).content).toEqual(saved.content);

  const prints = await installPrintProbe(page);
  await page.locator("#document-print").click(); await expect(page.locator("#print-submit")).toBeEnabled();
  await expect(page.locator("#print-preview [data-image-position=behind]")).toHaveCount(2);
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1);
  expect(prints[0].snapshot.html).toContain('data-image-position="behind"');
});

test("Office free positioning validates limits and resets to normal flow without a phantom edit", async ({ page }) => {
  await fixture(page); const editor = officeEditor(page), node = editor.locator(":scope > .office-image-node").first();
  await node.locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  for (const [field, value] of [["#image-position-x", "1001"], ["#image-position-y", "-1201"], ["#image-position-y", "1201"]]) {
    await page.locator(field).fill(value); await page.locator("#image-apply").click(); await expect(page.locator("#image-dialog")).toBeVisible();
  }
  await page.locator("#image-position-y").fill("34"); await page.locator("#image-position-x").fill("120");
  await page.locator("#image-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled();
  await node.locator(".office-image-anchor").click(); await page.locator("#image-options").click();
  await page.locator("#image-position-layer").selectOption("flow"); await expect(page.locator("#image-wrap")).toBeEnabled();
  await page.locator("#image-apply").click(); await expect(node).not.toHaveAttribute("data-image-position");
  await editor.press("Control+z"); await expect(node).toHaveAttribute("data-image-position", "front");
});
