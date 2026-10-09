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
  await page.locator("#shape-font-size").fill("28"); await page.locator("#shape-text-color").selectOption("purple");
  await page.locator("#shape-text-style").selectOption("boldItalic");
  await page.locator("#shape-rotation").fill("90");
  await page.locator("#shape-position-layer").selectOption("front");
  await page.locator("#shape-position-x").fill("500"); await page.locator("#shape-position-y").fill("24");
  await page.locator("#shape-text").fill("Edited ellipse"); await page.locator("#shape-apply").click();
  await expect(shape).toHaveAttribute("data-shape-kind", "ellipse"); await expect(shape).toHaveAttribute("data-shape-rotation", "90");
  await expect(shape).toHaveAttribute("data-shape-font-size", "28"); await expect(shape).toHaveAttribute("data-shape-text-color", "purple");
  await expect(shape).toHaveAttribute("data-shape-text-style", "boldItalic"); await expect(shape).toHaveCSS("font-size", "28px");
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
    kind: "ellipse", width: 450, height: 190, fill: "teal", stroke: "blue", strokeWidth: 4, text: "Edited ellipse", textAlign: "center",
    fontSize: 28, textColor: "purple", textStyle: "boldItalic", rotation: 180,
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
  await expect(page.locator("#print-preview .office-print-shape")).toHaveCSS("font-size", "28px");
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

test("Office shapes rotate at exact arbitrary angles by dialog keyboard and pointer", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Arbitrary shape rotation", "Rotation anchor");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-width").fill("320"); await page.locator("#shape-height").fill("160");
  await page.locator("#shape-text").fill("Rotated 37 degrees"); await page.locator("#shape-rotation").fill("37");
  await expect(page.locator("#shape-preview")).toHaveAttribute("data-shape-rotation", "37");
  await page.locator("#shape-apply").click();

  const node = editor.locator(".office-shape-node"), shape = node.locator(".office-shape");
  await expect(shape).toHaveAttribute("data-shape-rotation", "37");
  await expect(node).toHaveAttribute("data-shape-rotated", "");
  await expect(node).not.toHaveAttribute("data-shape-sideways", "");
  await expect(shape).toHaveCSS("transform", /matrix/);

  await shape.click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-rotation")).toHaveValue("37");
  await page.locator("#shape-rotation").fill("360"); await expect(page.locator("#shape-apply")).toBeDisabled();
  await page.locator("#shape-rotation").fill("359"); await expect(page.locator("#shape-apply")).toBeEnabled();
  await page.locator("#shape-apply").click(); await expect(shape).toHaveAttribute("data-shape-rotation", "359");

  let rotate = node.locator(".office-shape-rotate"); await rotate.focus(); await rotate.press("ArrowRight");
  await expect(shape).not.toHaveAttribute("data-shape-rotation", /.+/);
  await editor.press("Control+z"); await expect(shape).toHaveAttribute("data-shape-rotation", "359");
  await editor.press("Control+Shift+z"); await expect(shape).not.toHaveAttribute("data-shape-rotation", /.+/);
  rotate = node.locator(".office-shape-rotate"); await rotate.focus(); await rotate.press("Shift+ArrowLeft");
  await expect(shape).toHaveAttribute("data-shape-rotation", "345");

  const geometry = await node.evaluate((element) => {
    const shapeBox = element.querySelector(".office-shape").getBoundingClientRect();
    const handleBox = element.querySelector(".office-shape-rotate").getBoundingClientRect();
    const center = { x: shapeBox.left + shapeBox.width / 2, y: shapeBox.top + shapeBox.height / 2 };
    const start = { x: handleBox.left + handleBox.width / 2, y: handleBox.top + handleBox.height / 2 };
    const end = { x: center.x + Math.max(80, shapeBox.width / 2 + 40), y: center.y };
    const angle = (point) => Math.atan2(point.y - center.y, point.x - center.x) * 180 / Math.PI;
    const delta = ((angle(end) - angle(start) + 540) % 360) - 180;
    return { start, end, expected: ((345 + Math.round(delta)) % 360 + 360) % 360 };
  });
  await page.mouse.move(geometry.start.x, geometry.start.y); await page.mouse.down();
  await page.mouse.move(geometry.end.x, geometry.end.y, { steps: 6 }); await page.mouse.up();
  if (geometry.expected) await expect(shape).toHaveAttribute("data-shape-rotation", String(geometry.expected));
  else await expect(shape).not.toHaveAttribute("data-shape-rotation", /.+/);
  await editor.press("Control+z"); await expect(shape).toHaveAttribute("data-shape-rotation", "345");
  await editor.press("Control+Shift+z");
  if (geometry.expected) await expect(shape).toHaveAttribute("data-shape-rotation", String(geometry.expected));

  const saved = await saveOffice(page, { objectId });
  expect(saved.content.content.find((entry) => entry.type === "shape").attrs.rotation).toBe(geometry.expected || undefined);
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await page.locator("#document-print").click();
  if (geometry.expected % 180) await expect(page.locator("#print-preview .office-print-shape-node")).toHaveAttribute("data-shape-rotated", "");
  if (geometry.expected) await expect(page.locator("#print-preview .office-print-shape")).toHaveAttribute("data-shape-rotation", String(geometry.expected));
  await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-arbitrary-rotation-${testInfo.project.name}.png`, fullPage: true });
});

test("Office shape groups preserve ordered members history print and independent copies", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape group proof", "Text before shapes");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Alpha"); await page.locator("#shape-apply").click();
  await expect(editor.locator(".office-shape")).toHaveCount(1);
  await editor.locator(".office-shape").click(); await editor.press("ArrowRight");
  await expect(page.locator("#shape-options")).toHaveText("Form einfügen …");
  await page.locator("#shape-options").click(); await page.locator("#shape-kind").selectOption("ellipse");
  await page.locator("#shape-text").fill("Beta"); await page.locator("#shape-rotation").fill("143");
  await page.locator("#shape-font-size").fill("24"); await page.locator("#shape-text-color").selectOption("blue");
  await page.locator("#shape-text-style").selectOption("bold");
  await page.locator("#shape-apply").click(); await expect(editor.locator(".office-shape")).toHaveCount(2);

  await editor.locator(".office-shape").nth(1).click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-previous")).toBeEnabled();
  await page.locator("#shape-group-layout").selectOption("row"); await page.locator("#shape-group-gap").fill("16");
  await page.locator("#shape-group-previous").click();
  await expect(editor.locator(".office-shape-group")).toHaveCount(1);
  await expect(editor.locator(".office-shape-group .office-shape")).toHaveCount(2);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(0);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(1);

  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-position-layer")).toBeDisabled(); await expect(page.locator("#shape-wrap")).toBeDisabled();
  await expect(page.locator("#shape-group-member-previous")).toBeDisabled();
  await expect(page.locator("#shape-group-member-next")).toBeEnabled();
  await page.locator("#shape-group-member-next").click();
  await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Beta", "Alpha"]);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Alpha", "Beta"]);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Beta", "Alpha"]);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Alpha", "Beta"]);

  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-layout").selectOption("stack"); await page.locator("#shape-group-gap").fill("24");
  await page.locator("#shape-group-connection").selectOption("doubleArrow");
  await page.locator("#shape-group-connection-color").selectOption("purple");
  await page.locator("#shape-group-connection-width").fill("4");
  await page.locator("#shape-apply").click();
  await expect(editor.locator(".office-shape-group")).toHaveAttribute("data-shape-group-layout", "stack");
  await expect(editor.locator(".office-shape-group")).toHaveAttribute("data-shape-group-connection", "doubleArrow");
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-duplicate")).toBeEnabled(); await page.locator("#shape-duplicate").click();
  await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Alpha", "Alpha", "Beta"]);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveCount(2);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveCount(3);
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-alignment").selectOption("center");
  await page.locator("#shape-group-distribution").selectOption("even");
  await expect(page.locator("#shape-group-distribution-extent")).toBeEnabled();
  await page.locator("#shape-group-distribution-extent").fill("900");
  await expect(page.locator("#shape-group-connection-scope option")).toHaveText(["Alle Verbindungen", "1 → 2", "2 → 3"]);
  await page.locator("#shape-group-connection-scope").selectOption("edge-0");
  await page.locator("#shape-group-connection").selectOption("arrow");
  await page.locator("#shape-group-connection-color").selectOption("red");
  await page.locator("#shape-group-connection-width").fill("3"); await page.locator("#shape-apply").click();
  const alignedGroup = editor.locator(".office-shape-group");
  await expect(alignedGroup).toHaveAttribute("data-shape-group-alignment", "center");
  await expect(alignedGroup).toHaveAttribute("data-shape-group-distributed", "");
  await expect(alignedGroup.locator(".office-shape-group-content")).toHaveCSS("align-items", "center");
  expect(Number.parseInt(await alignedGroup.evaluate((element) => element.style.getPropertyValue("--shape-group-gap")), 10)).toBeGreaterThan(24);
  await editor.press("Control+z"); await expect(alignedGroup).toHaveAttribute("data-shape-group-alignment", "start");
  await expect(alignedGroup).not.toHaveAttribute("data-shape-group-distributed", "");
  await editor.press("Control+Shift+z"); await expect(alignedGroup).toHaveAttribute("data-shape-group-alignment", "center");
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-connection-scope").selectOption("edge-1");
  await page.locator("#shape-group-connection").selectOption("line");
  await page.locator("#shape-group-connection-color").selectOption("blue");
  await page.locator("#shape-group-connection-width").fill("5"); await page.locator("#shape-apply").click();
  const connectedMembers = editor.locator(".office-shape-group .office-shape-node");
  await expect(connectedMembers.nth(0)).toHaveAttribute("data-shape-group-connection", "arrow");
  await expect(connectedMembers.nth(1)).toHaveAttribute("data-shape-group-connection", "line");
  await expect(connectedMembers.nth(2)).not.toHaveAttribute("data-shape-group-connection", /.+/);
  const grouped = await saveOffice(page, { objectId });
  const group = grouped.content.content.find((entry) => entry.type === "shapeGroup");
  expect(group).toMatchObject({ attrs: { layout: "stack", gap: 24, alignment: "center", distributionExtent: 900, connections: [
    { kind: "arrow", color: "red", width: 3 }, { kind: "line", color: "blue", width: 5 },
  ] }, content: [
    { type: "shape", attrs: { text: "Alpha" } },
    { type: "shape", attrs: { text: "Alpha" } },
    { type: "shape", attrs: { text: "Beta", fontSize: 24, textColor: "blue", textStyle: "bold", rotation: 143 } },
  ] });
  expect(new Set(group.content.map((entry) => entry.attrs.id)).size).toBe(3);
  const prints = await installPrintProbe(page); await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-shape-group")).toHaveAttribute("data-shape-group-layout", "stack");
  await expect(page.locator("#print-preview .office-print-shape-group")).toHaveAttribute("data-shape-group-alignment", "center");
  await expect(page.locator("#print-preview .office-print-shape-group")).toHaveAttribute("data-shape-group-distributed", "");
  const printMembers = page.locator("#print-preview .office-print-shape-member");
  await expect(printMembers.nth(0)).toHaveAttribute("data-shape-group-connection", "arrow");
  await expect(printMembers.nth(1)).toHaveAttribute("data-shape-group-connection", "line");
  await expect(printMembers.nth(2)).not.toHaveAttribute("data-shape-group-connection", /.+/);
  await expect(page.locator("#print-preview .office-print-shape-group .office-print-shape")).toHaveCount(3);
  await expect(page.locator("#print-preview .office-print-shape-group .office-print-shape").nth(2)).toHaveCSS("font-size", "24px");
  await page.locator("#print-preview .office-print-shape-group").screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-alignment-print-${testInfo.project.name}.png` });
  await page.locator("#print-submit").click(); await expect.poll(() => prints.length).toBe(1); await page.locator("#print-close").click();
  await editor.locator(".office-shape-group").screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-per-edge-${testInfo.project.name}.png` });
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-${testInfo.project.name}.png`, fullPage: true });

  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-ungroup").click(); await expect(editor.locator(".office-shape-group")).toHaveCount(0);
  const ungrouped = await saveOffice(page, { objectId }); expect(ungrouped.version.previous_version_id).toBe(grouped.version.version_id);
  await openReuseHistory(page, grouped); await openReuse(page, grouped, "Independent shape group copy"); await submitReuse(page, grouped);
  await expectReuseDraft(page, "Independent shape group copy"); await expect(editor.locator(".office-shape-group .office-shape")).toHaveCount(3);
  const copy = await saveOffice(page); expect(copy.document.object_id).not.toBe(objectId);
  expect(copy.content.content.find((entry) => entry.type === "shapeGroup")).toEqual(group);
});

test("Office shape groups move freely as one object with history print and offset copies", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Positioned shape group proof", "Text around positioned group");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Position A"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await editor.press("ArrowRight"); await page.locator("#shape-options").click();
  await page.locator("#shape-kind").selectOption("ellipse"); await page.locator("#shape-rotation").fill("37");
  await page.locator("#shape-text").fill("Position B"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").nth(1).click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-previous").click();

  const group = editor.locator(".office-shape-group").first();
  await group.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-position-layer")).toBeEnabled();
  await expect(page.locator("#shape-group-position-x")).toBeDisabled();
  await page.locator("#shape-group-position-layer").selectOption("front");
  await page.locator("#shape-group-position-x").fill("400"); await page.locator("#shape-group-position-y").fill("80");
  await expect(page.locator("#shape-group-ungroup")).toBeDisabled(); await page.locator("#shape-apply").click();
  await expect(group).toHaveAttribute("data-shape-group-positioned", "");
  await expect(group).toHaveAttribute("data-shape-group-position", "front");
  const anchor = group.locator(".office-shape-group-anchor"); await expect(anchor).toBeVisible();
  await anchor.focus(); await anchor.press("Shift+ArrowRight"); await anchor.press("ArrowDown");
  await expect(anchor).toHaveAttribute("aria-label", /X 410; Y 81 Pixel/);
  await editor.press("Control+z"); await expect(anchor).toHaveAttribute("aria-label", /X 410; Y 80 Pixel/);
  await editor.press("Control+Shift+z"); await expect(anchor).toHaveAttribute("aria-label", /X 410; Y 81 Pixel/);
  const handle = await anchor.boundingBox(); expect(handle).not.toBeNull();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2); await page.mouse.down();
  await expect(anchor).toHaveAttribute("data-shape-group-dragging", "");
  await page.mouse.move(handle.x + handle.width / 2 + 24, handle.y + handle.height / 2 + 12);
  await expect(anchor).toHaveAttribute("aria-label", /Y 93 Pixel/); await page.mouse.up();
  await expect(anchor).not.toHaveAttribute("data-shape-group-dragging", "");

  await group.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-duplicate").click(); await expect(editor.locator(".office-shape-group")).toHaveCount(2);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(1);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(2);
  const saved = await saveOffice(page, { objectId }), groups = saved.content.content.filter((entry) => entry.type === "shapeGroup");
  expect(groups).toHaveLength(2); expect(groups[0].attrs.position.layer).toBe("front");
  expect(groups[0].attrs.position.y).toBe(93);
  expect(groups[1].attrs.position).toEqual({ layer: "front", x: groups[0].attrs.position.x + 25, y: 117 });
  expect(groups[1].attrs.id).not.toBe(groups[0].attrs.id);
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-shape-group[data-shape-group-positioned]")).toHaveCount(2);
  await expect(page.locator("#print-preview .office-print-shape-group").first()).toHaveAttribute("data-shape-group-position", "front");
  await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-position-live-${testInfo.project.name}.png`, fullPage: true });

  await group.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-position-layer").selectOption("flow"); await page.locator("#shape-apply").click();
  await group.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-ungroup")).toBeEnabled(); await page.locator("#shape-group-ungroup").click();
  await expect(editor.locator(".office-shape-group")).toHaveCount(1);
  await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(2);
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-remove").click(); await expect(editor.locator(".office-shape-group")).toHaveCount(0);
  await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(3);
  await expect(editor.locator(":scope > .office-shape-node[data-shape-positioned]")).toHaveCount(1);
  const promoted = await saveOffice(page, { objectId });
  expect(promoted.content.content.filter((entry) => entry.type === "shape").find((entry) => entry.attrs.position)?.attrs.position)
    .toEqual(groups[1].attrs.position);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-position-${testInfo.project.name}.png`, fullPage: true });
});

test("Office positioned shape duplication creates a visible independent copy", async ({ page }) => {
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape duplicate proof", "Text before copy");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Offset copy"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-position-layer").selectOption("front");
  await page.locator("#shape-position-x").fill("990"); await page.locator("#shape-position-y").fill("1190");
  await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-duplicate")).toBeEnabled(); await page.locator("#shape-duplicate").click();
  await expect(editor.locator(".office-shape")).toHaveCount(2);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape")).toHaveCount(1);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape")).toHaveCount(2);
  const saved = await saveOffice(page, { objectId }), shapes = saved.content.content.filter((entry) => entry.type === "shape");
  expect(shapes).toHaveLength(2); expect(shapes[0].attrs.position).toEqual({ layer: "front", x: 990, y: 1190 });
  expect(shapes[1].attrs.position).toEqual({ layer: "front", x: 965, y: 1166 });
  expect(shapes[1].attrs.id).not.toBe(shapes[0].attrs.id);
  const first = { ...shapes[0].attrs }; delete first.id; delete first.position;
  const second = { ...shapes[1].attrs }; delete second.id; delete second.position; expect(second).toEqual(first);
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-shape")).toHaveCount(2);
  await page.locator("#print-close").click();
});

test("Office shape group duplication preserves presentation with fresh identities", async ({ page }, testInfo) => {
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape group duplicate proof", "Group copy");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Source A"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await editor.press("ArrowRight"); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Source B"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").nth(1).click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-layout").selectOption("stack"); await page.locator("#shape-group-gap").fill("12");
  await page.locator("#shape-group-connection").selectOption("arrow");
  await page.locator("#shape-group-connection-color").selectOption("green");
  await page.locator("#shape-group-connection-width").fill("3"); await page.locator("#shape-group-previous").click();
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-duplicate")).toBeEnabled(); await page.locator("#shape-group-duplicate").click();
  await expect(editor.locator(".office-shape-group")).toHaveCount(2);
  await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Source A", "Source B", "Source A", "Source B"]);
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(1);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(2);
  const saved = await saveOffice(page, { objectId }), groups = saved.content.content.filter((entry) => entry.type === "shapeGroup");
  expect(groups).toHaveLength(2); expect(groups[1].attrs.id).not.toBe(groups[0].attrs.id);
  expect(new Set(groups.flatMap((group) => group.content.map((entry) => entry.attrs.id))).size).toBe(4);
  const withoutIds = (group) => ({ attrs: { ...group.attrs, id: undefined },
    content: group.content.map((entry) => ({ ...entry, attrs: { ...entry.attrs, id: undefined } })) });
  expect(withoutIds(groups[1])).toEqual(withoutIds(groups[0]));
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-shape-group")).toHaveCount(2);
  await expect(page.locator("#print-preview .office-print-shape")).toHaveCount(4); await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-duplicate-${testInfo.project.name}.png`, fullPage: true });
});

test("Office shape group removal is atomic and reversible", async ({ page }, testInfo) => {
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape group removal proof", "Keep this paragraph");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Remove A"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await editor.press("ArrowRight"); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Remove B"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").nth(1).click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-layout").selectOption("row"); await page.locator("#shape-group-gap").fill("18");
  await page.locator("#shape-group-connection").selectOption("doubleArrow"); await page.locator("#shape-group-previous").click();
  const grouped = await saveOffice(page, { objectId });
  const storedGroup = grouped.content.content.find((entry) => entry.type === "shapeGroup");
  expect(storedGroup.content.map((entry) => entry.attrs.text)).toEqual(["Remove A", "Remove B"]);
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-remove")).toBeEnabled(); await page.locator("#shape-group-remove").click();
  await expect(page.locator("#shape-status")).not.toContainText("erneut auswählen");
  await expect(page.locator("#shape-status")).not.toContainText("schreibgeschützt");
  await expect(page.locator("#shape-status")).not.toContainText("nicht gefunden");
  await expect(editor.locator(".office-shape-group")).toHaveCount(0); await expect(editor.locator(".office-shape")).toHaveCount(0);
  await expect(editor).toContainText("Keep this paragraph");
  await editor.press("Control+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(1);
  await expect(editor.locator(".office-shape-group .office-shape")).toHaveText(["Remove A", "Remove B"]);
  await editor.press("Control+Shift+z"); await expect(editor.locator(".office-shape-group")).toHaveCount(0);
  const saved = await saveOffice(page, { objectId });
  expect(saved.version.previous_version_id).toBe(grouped.version.version_id);
  expect(saved.content.content.some((entry) => entry.type === "shapeGroup" || entry.type === "shape")).toBeFalsy();
  expect((await officeContent(page, objectId, { versionId: grouped.version.version_id })).content.content
    .find((entry) => entry.type === "shapeGroup")).toEqual(storedGroup);
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-shape-group")).toHaveCount(0);
  await expect(page.locator("#print-preview")).toContainText("Keep this paragraph"); await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-remove-${testInfo.project.name}.png`, fullPage: true });
});

test("Office shape groups move atomically in document order", async ({ page }, testInfo) => {
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape group order proof", "Paragraph before group");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Order A"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").click(); await editor.press("ArrowRight"); await page.locator("#shape-options").click();
  await page.locator("#shape-text").fill("Order B"); await page.locator("#shape-apply").click();
  await editor.locator(".office-shape").nth(1).click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-layout").selectOption("row"); await page.locator("#shape-group-gap").fill("20");
  await page.locator("#shape-group-connection").selectOption("arrow"); await page.locator("#shape-group-previous").click();
  const originalId = await editor.locator(".office-shape-group").getAttribute("data-shape-group");
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-move-previous")).toBeEnabled();
  await expect(page.locator("#shape-group-move-next")).toBeDisabled();
  await page.locator("#shape-group-move-previous").click();
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(1);
  await expect(editor.locator(":scope > *").first()).toHaveClass(/office-shape-group/);
  await editor.press("Control+z"); await expect(editor.locator(":scope > p").first()).toContainText("Paragraph before group");
  await editor.press("Control+Shift+z"); await expect(editor.locator(":scope > *").first()).toHaveClass(/office-shape-group/);
  await editor.locator(".office-shape-group-control").click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-group-move-previous")).toBeDisabled();
  await expect(page.locator("#shape-group-move-next")).toBeEnabled(); await page.locator("#shape-group-move-next").click();
  await expect(editor.locator(":scope > p").first()).toContainText("Paragraph before group");
  const saved = await saveOffice(page, { objectId }), group = saved.content.content.find((entry) => entry.type === "shapeGroup");
  expect(saved.content.content.map((entry) => entry.type)).toEqual(["paragraph", "shapeGroup"]);
  expect(group.attrs.id).toBe(originalId); expect(group.attrs).toMatchObject({ layout: "row", gap: 20, connection: { kind: "arrow" } });
  expect(group.content.map((entry) => entry.attrs.text)).toEqual(["Order A", "Order B"]);
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-content > p").first()).toContainText("Paragraph before group");
  await expect(page.locator("#print-preview .office-print-shape-group .office-print-shape")).toHaveText(["Order A", "Order B"]);
  await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-group-order-${testInfo.project.name}.png`, fullPage: true });
});

test("Office standalone shapes move atomically in document order", async ({ page }, testInfo) => {
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape order proof", "Paragraph before shape");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#shape-options").click();
  await page.locator("#shape-kind").selectOption("roundedRectangle");
  await page.locator("#shape-width").fill("360"); await page.locator("#shape-height").fill("140");
  await page.locator("#shape-fill").selectOption("yellow"); await page.locator("#shape-stroke").selectOption("purple");
  await page.locator("#shape-stroke-width").fill("4"); await page.locator("#shape-font-size").fill("24");
  await page.locator("#shape-text-color").selectOption("blue"); await page.locator("#shape-text-style").selectOption("bold");
  await page.locator("#shape-text").fill("Ordered standalone shape"); await page.locator("#shape-apply").click();
  const shape = editor.locator(".office-shape");
  const originalId = await shape.getAttribute("data-office-shape");
  await shape.click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-move-previous")).toBeEnabled();
  await expect(page.locator("#shape-move-next")).toBeDisabled();
  await page.locator("#shape-move-previous").click();
  await expect(editor.locator(":scope > *").first()).toHaveClass(/office-shape-node/);
  await editor.press("Control+z"); await expect(editor.locator(":scope > p").first()).toContainText("Paragraph before shape");
  await editor.press("Control+Shift+z"); await expect(editor.locator(":scope > *").first()).toHaveClass(/office-shape-node/);
  await shape.click(); await page.locator("#shape-options").click();
  await expect(page.locator("#shape-move-previous")).toBeDisabled();
  await expect(page.locator("#shape-move-next")).toBeEnabled(); await page.locator("#shape-move-next").click();
  await expect(editor.locator(":scope > p").first()).toContainText("Paragraph before shape");
  const saved = await saveOffice(page, { objectId }), stored = saved.content.content.find((entry) => entry.type === "shape");
  expect(saved.content.content.map((entry) => entry.type)).toEqual(["paragraph", "shape"]);
  expect(stored.attrs).toMatchObject({ id: originalId, kind: "roundedRectangle", width: 360, height: 140,
    fill: "yellow", stroke: "purple", strokeWidth: 4, fontSize: 24, textColor: "blue", textStyle: "bold",
    text: "Ordered standalone shape" });
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-content > p").first()).toContainText("Paragraph before shape");
  await expect(page.locator("#print-preview .office-print-shape")).toContainText("Ordered standalone shape");
  await page.locator("#print-close").click();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-order-${testInfo.project.name}.png`, fullPage: true });
});

test("Office shapes and groups support atomic responsive multi-selection", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native shape multi-selection proof", "Keep this paragraph");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  const insertShape = async (text, kind = "rectangle") => {
    await page.locator("#shape-options").click(); await page.locator("#shape-kind").selectOption(kind);
    await page.locator("#shape-text").fill(text); await page.locator("#shape-apply").click();
  };
  await editor.locator("p").click(); await insertShape("Multi A", "roundedRectangle");
  await editor.locator(":scope > .office-shape-node .office-shape").last().click(); await editor.press("ArrowRight"); await insertShape("Multi B");
  await editor.locator(":scope > .office-shape-node .office-shape").last().click(); await editor.press("ArrowRight"); await insertShape("Multi C", "ellipse");
  await editor.locator(":scope > .office-shape-node .office-shape").last().click(); await page.locator("#shape-options").click();
  await page.locator("#shape-group-layout").selectOption("stack"); await page.locator("#shape-group-gap").fill("20");
  await page.locator("#shape-group-connection").selectOption("arrow"); await page.locator("#shape-group-previous").click();
  await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(1);
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(1);

  await page.locator("#shape-multi-toggle").click(); await expect(page.locator("#shape-multi-toggle")).toHaveAttribute("aria-pressed", "true");
  await editor.locator(":scope > .office-shape-node .office-shape").click();
  await editor.locator(":scope > .office-shape-group .office-shape-group-control").click();
  await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(2);
  await expect(page.locator("#shape-multi-status")).toHaveText("2 Objekte ausgewählt");
  await expect(page.locator("#shape-multi-group")).toBeDisabled();
  await expect(page.locator("#shape-multi-duplicate")).toBeEnabled(); await page.locator("#shape-multi-duplicate").click();
  await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(2);
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(2);
  await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(2);
  await editor.press("Control+z"); await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(1);
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(1);
  await editor.press("Control+Shift+z"); await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(2);
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(2);

  await editor.locator(":scope > .office-shape-node .office-shape").nth(0).click();
  await editor.locator(":scope > .office-shape-node .office-shape").nth(1).click();
  await expect(page.locator("#shape-multi-group")).toBeEnabled(); await page.locator("#shape-multi-group").click();
  await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(0);
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(3);
  await editor.press("Control+z"); await expect(editor.locator(":scope > .office-shape-node")).toHaveCount(2);
  await editor.press("Control+Shift+z"); await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(3);

  const controls = editor.locator(":scope > .office-shape-group .office-shape-group-control");
  await controls.nth(0).click(); await controls.nth(1).click();
  await expect(page.locator("#shape-multi-remove")).toBeEnabled(); await page.locator("#shape-multi-remove").click();
  await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(1);
  await editor.press("Control+z"); await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(3);
  await editor.press("Control+Shift+z"); await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(1);
  await editor.press("Control+z"); await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(3);

  const saved = await saveOffice(page, { objectId }), groups = saved.content.content.filter((entry) => entry.type === "shapeGroup");
  expect(saved.version.previous_version_id).toBe(baseline.version.version_id); expect(groups).toHaveLength(3);
  expect(groups.flatMap((group) => group.content)).toHaveLength(6);
  expect(new Set(groups.flatMap((group) => group.content.map((entry) => entry.attrs.id))).size).toBe(6);
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-shape-group")).toHaveCount(3);
  await expect(page.locator("#print-preview .office-print-shape")).toHaveCount(6); await page.locator("#print-close").click();
  await page.locator("#document-reload").click(); await expect(editor.locator(":scope > .office-shape-group")).toHaveCount(3);
  await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(0);
  await expect(page.locator("#shape-multi-toggle")).toHaveAttribute("aria-pressed", "false");
  await controls.nth(0).click({ modifiers: ["Control"] }); await controls.nth(2).click({ modifiers: ["Shift"] });
  await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(3);
  await page.keyboard.press("Escape"); await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(0);
  await openReuse(page, saved, "Independent multi-selection result");
  await submitReuse(page, saved); await expectReuseDraft(page, "Independent multi-selection result");
  await expect(officeEditor(page).locator(":scope > .office-shape-group")).toHaveCount(3);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-multi-selection-${testInfo.project.name}.png`, fullPage: true });
});

test("Office positioned root objects align distribute layer nudge and drag atomically", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native positioned object arrangement proof", "Anchor paragraph");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  const insertPositioned = async (text, x, y, layer = "front") => {
    await page.locator("#shape-options").click();
    await page.locator("#shape-text").fill(text);
    await page.locator("#shape-position-layer").selectOption(layer);
    await page.locator("#shape-position-x").fill(String(x));
    await page.locator("#shape-position-y").fill(String(y));
    await page.locator("#shape-apply").click();
  };
  await editor.locator("p").click(); await insertPositioned("Arrange A", 100, -300); await editor.press("ArrowRight");
  await insertPositioned("Arrange B", 900, 200, "behind"); await editor.press("ArrowRight");
  await insertPositioned("Arrange C", 300, 900);
  const shapes = editor.locator(":scope > .office-shape-node");
  await expect(shapes).toHaveCount(3);

  await page.locator("#shape-multi-toggle").click();
  for (const shape of await editor.locator(":scope > .office-shape-node .office-shape").all()) {
    await shape.dispatchEvent("click");
  }
  await expect(page.locator("#shape-multi-status")).toHaveText("3 Objekte ausgewählt");
  await expect(page.locator("#shape-multi-group")).toBeDisabled();
  await expect(page.locator("#shape-multi-align")).toBeEnabled();
  await expect(page.locator("#shape-multi-distribute")).toBeEnabled();

  await page.locator("#shape-multi-align").selectOption("horizontal:center");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50%", "50%", "50%"]);
  await editor.press("Control+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["10%", "90%", "30%"]);
  await editor.press("Control+Shift+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50%", "50%", "50%"]);

  await page.locator("#shape-multi-distribute").selectOption("vertical");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-y"))))
    .toEqual(["-300px", "300px", "900px"]);
  await editor.press("Control+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-y"))))
    .toEqual(["-300px", "200px", "900px"]);
  await editor.press("Control+Shift+z");

  await page.locator("#shape-multi-layer").selectOption("front");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").dataset.shapePosition))).toEqual(["front", "front", "front"]);
  await editor.press("Control+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").dataset.shapePosition))).toEqual(["front", "behind", "front"]);
  await editor.press("Control+Shift+z");

  await editor.press("ArrowRight");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50.1%", "50.1%", "50.1%"]);
  await editor.press("Control+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50%", "50%", "50%"]);
  await editor.press("Control+Shift+z");
  await editor.press("Shift+ArrowDown");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-y"))))
    .toEqual(["-290px", "310px", "910px"]);
  await editor.press("Control+z"); await editor.press("Control+Shift+z");

  const dragAnchor = shapes.nth(1).locator(".office-shape-anchor");
  await expect(dragAnchor).toHaveAttribute("aria-label", "3 ausgewählte Objekte gemeinsam ziehen; Maus oder Touch");
  const editorWidth = await editor.evaluate((element) => element.getBoundingClientRect().width);
  const pointerType = testInfo.project.name.includes("mobile") ? "touch" : "mouse";
  const drag = async (pointerId, endType) => {
    await dragAnchor.dispatchEvent("pointerdown", { pointerId, pointerType, isPrimary: true, button: 0, buttons: 1,
      clientX: 240, clientY: 240 });
    await editor.dispatchEvent("pointermove", { pointerId, pointerType, isPrimary: true, button: 0, buttons: 1,
      clientX: 240 + editorWidth * 0.08, clientY: 280 });
    await expect(editor.locator("[data-office-multi-dragging]")).toHaveCount(3);
    await expect(page.locator("#shape-multi-status")).toHaveText("3 Objekte · X +80 · Y +40");
    await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
      entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
      .toEqual(["58.1%", "58.1%", "58.1%"]);
    await editor.dispatchEvent(endType, { pointerId, pointerType, isPrimary: true, button: 0, buttons: 0,
      clientX: 240 + editorWidth * 0.08, clientY: 280 });
  };
  await drag(41, "pointercancel");
  await expect(editor.locator("[data-office-multi-dragging]")).toHaveCount(0);
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50.1%", "50.1%", "50.1%"]);
  await drag(42, "pointerup");
  await expect(editor.locator("[data-office-multi-dragging]")).toHaveCount(0);
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-y"))))
    .toEqual(["-250px", "350px", "950px"]);
  await editor.press("Control+z");
  await expect.poll(() => shapes.evaluateAll((entries) => entries.map((entry) =>
    entry.querySelector(".office-shape").style.getPropertyValue("--office-shape-position-x"))))
    .toEqual(["50.1%", "50.1%", "50.1%"]);
  await editor.press("Control+Shift+z");

  const saved = await saveOffice(page, { objectId });
  const stored = saved.content.content.filter((entry) => entry.type === "shape");
  expect(stored.map((entry) => entry.attrs.position.x)).toEqual([581, 581, 581]);
  expect(stored.map((entry) => entry.attrs.position.y)).toEqual([-250, 350, 950]);
  expect(stored.map((entry) => entry.attrs.position.layer)).toEqual(["front", "front", "front"]);
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-shape")).toHaveCount(3);
  await page.locator("#print-close").click();
  await page.locator("#document-reload").click();
  await expect(editor.locator("[data-office-multi-selected]")).toHaveCount(0);
  await expect(page.locator("#shape-multi-toggle")).toHaveAttribute("aria-pressed", "false");
  await openReuse(page, saved, "Independent arranged objects"); await submitReuse(page, saved);
  await expectReuseDraft(page, "Independent arranged objects");
  await expect(officeEditor(page).locator(":scope > .office-shape-node")).toHaveCount(3);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-shape-multi-arrangement-${testInfo.project.name}.png`, fullPage: true });
});
