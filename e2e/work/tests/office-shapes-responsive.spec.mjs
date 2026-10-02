import { test, expect } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, openOffice, saveOffice, officeContent, officeEditor } from "./office-support.mjs";
import { installPrintProbe } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

test("Office shapes insert edit undo save print and copy responsively", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape proof", "Text before shape");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-dialog")).toBeVisible();
  await page.locator("#shape-kind").selectOption("roundedRectangle");
  await page.locator("#shape-width").fill("420"); await page.locator("#shape-height").fill("180");
  await page.locator("#shape-fill").selectOption("yellow"); await page.locator("#shape-stroke").selectOption("blue");
  await page.locator("#shape-stroke-width").fill("4"); await page.locator("#shape-text-align").selectOption("center");
  await page.locator("#shape-text").fill("Bounded literal <script> shape 😀");
  await expect(page.locator("#shape-preview")).toHaveAttribute("data-shape-kind", "roundedRectangle");
  await page.locator("#shape-apply").click();
  const shape = editor.locator(".office-shape"); await expect(shape).toHaveCount(1);
  await expect(shape).toContainText("<script>"); await expect(shape).toHaveAttribute("data-shape-fill", "yellow");
  const bounds = await shape.evaluate((element) => { const box = element.getBoundingClientRect(); return { width: box.width, viewport: innerWidth, overflow: document.documentElement.scrollWidth - innerWidth }; });
  expect(bounds.width).toBeLessThanOrEqual(bounds.viewport); expect(bounds.overflow).toBeLessThanOrEqual(0);

  await shape.click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-title")).toHaveText("Form bearbeiten");
  await page.locator("#shape-kind").selectOption("ellipse"); await page.locator("#shape-fill").selectOption("teal");
  await page.locator("#shape-rotation").selectOption("90");
  await page.locator("#shape-position-layer").selectOption("front");
  await page.locator("#shape-position-x").fill("500"); await page.locator("#shape-position-y").fill("24");
  await page.locator("#shape-text").fill("Edited ellipse"); await page.locator("#shape-apply").click();
  await expect(shape).toHaveAttribute("data-shape-kind", "ellipse"); await expect(shape).toHaveAttribute("data-shape-rotation", "90");
  await expect(editor.locator(".office-shape-node")).toHaveAttribute("data-shape-sideways", "");
  await expect(shape).toHaveText("Edited ellipse");
  await editor.press("Control+z"); await expect(shape).toHaveAttribute("data-shape-kind", "roundedRectangle");
  await editor.press("Control+Shift+z"); await expect(shape).toHaveAttribute("data-shape-kind", "ellipse");
  const anchor = editor.locator(".office-shape-anchor"); await expect(anchor).toContainText("vor Text");
  await anchor.focus(); await anchor.press("Shift+ArrowRight");
  await expect(shape).toHaveCSS("left", /.+/); await editor.press("Control+z"); await editor.press("Control+Shift+z");
  const resize = editor.locator(".office-shape-resize"); await expect(resize).toBeVisible();
  await resize.focus(); await resize.press("Shift+ArrowRight");
  await expect(resize).toHaveAttribute("aria-label", /430 mal 180/);
  await editor.press("Control+z"); await expect(resize).toHaveAttribute("aria-label", /420 mal 180/);
  await editor.press("Control+Shift+z"); await expect(resize).toHaveAttribute("aria-label", /430 mal 180/);
  const handle = await resize.boundingBox(); expect(handle).not.toBeNull();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2); await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 20, handle.y + handle.height / 2 + 10); await page.mouse.up();
  await expect(resize).toHaveAttribute("aria-label", /450 mal 190/);
  const rotate = editor.locator(".office-shape-rotate"); await expect(rotate).toBeVisible(); await rotate.click();
  await expect(shape).toHaveAttribute("data-shape-rotation", "180");
  await editor.press("Control+z"); await expect(shape).toHaveAttribute("data-shape-rotation", "90");
  await editor.press("Control+Shift+z"); await expect(shape).toHaveAttribute("data-shape-rotation", "180");

  const saved = await saveOffice(page, { objectId });
  expect(saved.content.content.find((entry) => entry.type === "shape")).toMatchObject({ attrs: {
    kind: "ellipse", width: 450, height: 190, fill: "teal", stroke: "blue", strokeWidth: 4, text: "Edited ellipse", textAlign: "center", rotation: 180,
    position: { layer: "front", x: 510, y: 24 },
  } });
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);

  await anchor.click(); await page.locator("#shape-options").click(); await page.locator("#shape-position-layer").selectOption("behind");
  await page.locator("#shape-apply").click(); await expect(anchor).toContainText("hinter Text");
  const behind = await saveOffice(page, { objectId });
  expect(behind.content.content.find((entry) => entry.type === "shape").attrs.position).toEqual({ layer: "behind", x: 510, y: 24 });
  const prints = await installPrintProbe(page); await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-shape")).toHaveAttribute("data-shape-position", "behind");
  await expect(page.locator("#print-preview .office-print-shape")).toHaveAttribute("data-shape-rotation", "180");
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1); await page.locator("#print-close").click();

  await anchor.click(); await page.locator("#shape-options").click(); await page.locator("#shape-position-layer").selectOption("flow");
  await page.locator("#shape-apply").click(); await expect(anchor).toHaveCount(0); const reset = await saveOffice(page, { objectId });
  expect(reset.content.content.find((entry) => entry.type === "shape").attrs.position).toBeUndefined();
  expect(reset.version.previous_version_id).toBe(behind.version.version_id);
  await shape.click(); await page.locator("#shape-options").click(); await expect(page.locator("#shape-wrap")).toBeEnabled();
  await page.locator("#shape-wrap").selectOption("right"); await page.locator("#shape-wrap-gap").fill("24"); await page.locator("#shape-apply").click();
  await expect(editor.locator(".office-shape-node")).toHaveAttribute("data-shape-wrap", "right");
  const wrapped = await saveOffice(page, { objectId });
  expect(wrapped.content.content.find((entry) => entry.type === "shape").attrs.wrap).toEqual({ side: "right", gap: 24 });
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-shape")).toHaveAttribute("data-shape-wrap", "right");
  await page.locator("#print-close").click(); await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-${testInfo.project.name}.png`, fullPage: true });
  await shape.click(); await page.locator("#shape-options").click(); await page.locator("#shape-wrap").selectOption("none");
  await page.locator("#shape-apply").click(); const unwrapped = await saveOffice(page, { objectId });
  expect(unwrapped.content.content.find((entry) => entry.type === "shape").attrs.wrap).toBeUndefined();
  await openReuseHistory(page, wrapped); await openReuse(page, wrapped, "Independent wrapped shape copy"); await submitReuse(page, wrapped);
  await expectReuseDraft(page, "Independent wrapped shape copy"); await expect(editor.locator(".office-shape")).toHaveText("Edited ellipse");
  const copy = await saveOffice(page); expect(copy.document.object_id).not.toBe(objectId);
  expect(copy.content.content.find((entry) => entry.type === "shape").attrs).toEqual(wrapped.content.content.find((entry) => entry.type === "shape").attrs);
});
