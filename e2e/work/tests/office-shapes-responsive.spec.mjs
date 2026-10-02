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
  await page.locator("#shape-text").fill("Edited ellipse"); await page.locator("#shape-apply").click();
  await expect(shape).toHaveAttribute("data-shape-kind", "ellipse"); await expect(shape).toHaveText("Edited ellipse");
  await editor.press("Control+z"); await expect(shape).toHaveAttribute("data-shape-kind", "roundedRectangle");
  await editor.press("Control+Shift+z"); await expect(shape).toHaveAttribute("data-shape-kind", "ellipse");

  const saved = await saveOffice(page, { objectId });
  expect(saved.content.content.find((entry) => entry.type === "shape")).toMatchObject({ attrs: {
    kind: "ellipse", width: 420, height: 180, fill: "teal", stroke: "blue", strokeWidth: 4, text: "Edited ellipse", textAlign: "center",
  } });
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);

  const prints = await installPrintProbe(page); await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-shape")).toHaveText("Edited ellipse");
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1); await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-${testInfo.project.name}.png`, fullPage: true });

  await shape.click(); await page.locator("#shape-options").click(); await page.locator("#shape-remove").click();
  await expect(shape).toHaveCount(0); const reset = await saveOffice(page, { objectId });
  expect(reset.version.previous_version_id).toBe(saved.version.version_id);
  await openReuseHistory(page, saved); await openReuse(page, saved, "Independent shape copy"); await submitReuse(page, saved);
  await expectReuseDraft(page, "Independent shape copy"); await expect(editor.locator(".office-shape")).toHaveText("Edited ellipse");
  const copy = await saveOffice(page); expect(copy.document.object_id).not.toBe(objectId);
  expect(copy.content.content.find((entry) => entry.type === "shape").attrs).toEqual(saved.content.content.find((entry) => entry.type === "shape").attrs);
});
