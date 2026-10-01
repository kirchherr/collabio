import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { openOffice, createOfficeDocument, saveOffice, officeEditor, officeContent, OFFICE_HEADERS } from "./office-support.mjs";
import { installPrintProbe } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });

async function fixture(page) {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Image group recovery", "Group introduction");
  const images = [];
  for (let index = 0; index < 3; index += 1) {
    const bytes = Buffer.from(await page.evaluate((entry) => {
      const colors = ["#0f766e", "#7c3aed", "#ea580c"], canvas = document.createElement("canvas");
      canvas.width = 240; canvas.height = 140; const context = canvas.getContext("2d");
      context.fillStyle = colors[entry]; context.fillRect(0, 0, 240, 140); context.fillStyle = "#fff";
      context.font = "bold 36px sans-serif"; context.fillText(String(entry + 1), 108, 84);
      return canvas.toDataURL().split(",")[1];
    }, index), "base64");
    const upload = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/images`, {
      data: bytes, headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
    });
    expect(upload.status()).toBe(200);
    images.push({ type: "image", attrs: { ...(await upload.json()).image, width: 180, height: 105,
      alt: `Grouped sample ${index + 1}`, decorative: false, caption: `Group image ${index + 1}` } });
  }
  const content = { type: "doc", content: [paragraph("Group introduction"), ...images, paragraph("Text after image group.")] };
  const saved = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: content,
      mutation_reference: `group-fixture-${first.document.object_id}`, expected_current_version_id: first.version.version_id, human_confirmation: true },
  });
  expect(saved.status()).toBe(200); await page.locator("#document-reload").click();
  await expect(officeEditor(page).locator("img")).toHaveCount(3);
  return { baseline: await saved.json(), images };
}

async function openImage(page, index = 0) {
  const groupControl = officeEditor(page).locator(".office-image-group-control");
  if (index === 0 && await groupControl.count()) await groupControl.click();
  else await officeEditor(page).locator("img").nth(index).click();
  await page.locator("#image-options").click();
  await expect(page.locator("#image-dialog")).toBeVisible();
}

async function expectResponsiveGroup(page) {
  const boxes = await officeEditor(page).locator(".office-image-group img").evaluateAll((nodes) => nodes.map((node) => {
    const box = node.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height };
  }));
  expect(boxes).toHaveLength(3);
  const narrow = await officeEditor(page).evaluate((node) => node.clientWidth <= 600);
  if (narrow) expect(boxes[1].y).toBeGreaterThanOrEqual(boxes[0].y + boxes[0].height);
  else { expect(Math.abs(boxes[1].y - boxes[0].y)).toBeLessThan(2); expect(boxes[1].x).toBeGreaterThan(boxes[0].x); }
}

test("Office image groups combine edit move delete undo save print ungroup and owned copy responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  const { baseline, images } = await fixture(page), editor = officeEditor(page), objectId = baseline.document.object_id;

  await openImage(page, 0);
  await expect(page.locator("#image-group-previous")).toBeDisabled();
  await expect(page.locator("#image-group-next")).toBeEnabled();
  await expect(page.locator("#image-group-ungroup")).toBeDisabled();
  await page.locator("#image-group-gap").fill("12"); await page.locator("#image-group-next").click();
  const group = editor.locator(":scope > .office-image-group");
  await expect(group).toHaveCount(1); await expect(group.locator("img")).toHaveCount(2);
  await expect(group).toHaveAttribute("data-image-group-layout", "row");
  await editor.press("Control+z"); await expect(group).toHaveCount(0);
  await editor.press("Control+Shift+z"); await expect(group.locator("img")).toHaveCount(2);

  await openImage(page, 0); await page.locator("#image-group-next").click();
  await expect(group.locator("img")).toHaveCount(3);
  await openImage(page, 0); await expect(page.locator("#image-wrap")).toBeDisabled();
  await expect(page.locator("#image-position-layer")).toBeDisabled();
  await page.locator("#image-remove").click(); await expect(group.locator("img")).toHaveCount(2);
  await editor.press("Control+z"); await expect(group.locator("img")).toHaveCount(3);

  await openImage(page, 0); await page.locator("#image-up").click();
  await expect(editor.locator(":scope > :first-child")).toHaveClass(/office-image-group/);
  await editor.press("Control+z"); await expect(editor.locator(":scope > :first-child")).toHaveText("Group introduction");
  await openImage(page, 0); await page.locator("#image-group-layout").selectOption("stack");
  await page.locator("#image-group-gap").fill("24"); await page.locator("#image-apply").click();
  await expect(group).toHaveAttribute("data-image-group-layout", "stack");
  await editor.press("Control+z"); await expect(group).toHaveAttribute("data-image-group-layout", "row");
  await editor.press("Control+Shift+z"); await expect(group).toHaveAttribute("data-image-group-layout", "stack");
  const grouped = await saveOffice(page, { objectId });
  expect(grouped.content.content[1]).toMatchObject({ type: "imageGroup", attrs: { layout: "stack", gap: 24 } });
  expect(grouped.content.content[1].content.map((entry) => entry.attrs)).toEqual(images.map((entry) => entry.attrs));
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);

  const prints = await installPrintProbe(page); await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-image-group[data-image-group-layout='stack'] img")).toHaveCount(3);
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1);
  expect(prints[0].snapshot.html).toContain("office-print-image-group"); await page.locator("#print-close").click();

  await openImage(page, 0); await page.locator("#image-group-layout").selectOption("row"); await page.locator("#image-apply").click();
  await expectResponsiveGroup(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-image-group-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await openImage(page, 0); await page.locator("#image-group-ungroup").click();
  await expect(group).toHaveCount(0); await expect(editor.locator(":scope > .office-image-node")).toHaveCount(3);
  const reset = await saveOffice(page, { objectId });
  expect(reset.content).toEqual(baseline.content); expect(reset.version.previous_version_id).toBe(grouped.version.version_id);

  await openReuseHistory(page, grouped); await openReuse(page, grouped, "Independent grouped copy");
  await submitReuse(page, grouped); await expectReuseDraft(page, "Independent grouped copy");
  await expect(editor.locator(".office-image-group img")).toHaveCount(3);
  const copy = await saveOffice(page), copied = copy.content.content.find((entry) => entry.type === "imageGroup");
  expect(copied.attrs).toEqual(grouped.content.content[1].attrs);
  expect(copied.content.map((entry) => entry.attrs.assetId)).not.toEqual(images.map((entry) => entry.attrs.assetId));
  expect(copied.content.map((entry) => entry.attrs.contentHash)).toEqual(images.map((entry) => entry.attrs.contentHash));
});
