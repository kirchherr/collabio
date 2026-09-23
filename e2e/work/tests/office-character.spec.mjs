import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { OFFICE_READER_ID, officeEditor, openOffice, openOfficeDocument, saveOffice, officeVersions,
  officeContent, setOfficeAcl, openOfficeComparison, loadOfficeComparison, officeFeatures, setOfficeFeatures, officeContentPath } from "./office-support.mjs";
import { createParagraphFixture, paragraph, richParagraphDocument, selectParagraphBlocks, paragraphWrites } from "./paragraph-helper.mjs";
import { applyCharacters, openCharacters, selectCharacters, expectCharacterStyle, characterDocument, characterMark, characterText } from "./character-helper.mjs";
import { openReuse, submitReuse, expectReuseDraft } from "./office-reuse-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint, expectPdfStructure, pdfPageCount, expectPrintCleared, openPrintHistory } from "./office-print-support.mjs";

test("Office changes only selected Unicode text and persists exact character formatting with one undo step", async ({ page }) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createParagraphFixture(page, "Character partial selection", characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 6, 13); // café plus emoji, complete UTF-16 boundaries
  await applyCharacters(page, { size: 24, color: "purple" });
  const spans = officeEditor(page).locator("span[data-office-font-size]");
  await expect(spans).toHaveCount(4);
  await expectCharacterStyle(spans.nth(1), 24, "purple");
  await expect(spans.nth(1)).toHaveText("café 😀");
  await officeEditor(page).press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(spans).toHaveCount(2);
  await officeEditor(page).press("Control+Shift+z");
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(second.content.content[0].content).toEqual([
    characterText("Alpha "), characterText("café 😀", { fontSize: 24, textColor: "purple" }), characterText(" "), characterText("Beta END", { fontSize: 12, textColor: "red" }),
  ]);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await page.locator("#document-close").click(); await openOfficeDocument(page, first.document.object_id);
  await expectCharacterStyle(spans.nth(1), 24, "purple");
  verify();
});

test("Office mixed character selection retains unchanged colors and supports explicit reset cancel and clean no-op", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character mixed selection", characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await openCharacters(page);
  await expect(page.locator("#character-size")).toHaveValue("mixed");
  await expect(page.locator("#character-color")).toHaveValue("mixed");
  await page.locator("#character-apply").click();
  await expect(page.locator("#character-status")).toContainText("Keine Änderung");
  await expect(page.locator("#document-save")).toBeDisabled();
  await page.locator("#character-size").selectOption("24");
  await page.locator("#character-apply").click();
  const spans = officeEditor(page).locator("span[data-office-font-size]");
  await expectCharacterStyle(spans.first(), 24, "blue"); await expectCharacterStyle(spans.last(), 24, "red");
  await openCharacters(page); await page.locator("#character-reset").click(); await page.keyboard.press("Escape");
  await expectCharacterStyle(spans.first(), 24, "blue");
  await applyCharacters(page, { size: "default", color: "default" });
  await expect(officeEditor(page).locator("[data-office-font-size],[data-office-text-color]")).toHaveCount(0);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content).toEqual({ type: "doc", content: [paragraph("Alpha café 😀 Beta END")] });
  await openCharacters(page); await page.locator("#character-apply").click();
  await expect(page.locator("#character-status")).toContainText("Keine Änderung");
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office character choices at the caret style subsequent typing without dirtying the saved document", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character typing", { type: "doc", content: [paragraph("Start")] });
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 5);
  await applyCharacters(page, { size: 18, color: "green" });
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await page.keyboard.type(" typed");
  await expectCharacterStyle(officeEditor(page).locator("span"), 18, "green");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page)).toHaveText("Start");
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  await selectCharacters(page, 0, 11);
  await applyCharacters(page, { size: "default", color: "default" });
  await page.keyboard.type(" plain");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content[0].content).toEqual([
    { type: "text", text: "Start" }, characterText(" typed", { fontSize: 18, textColor: "green" }), { type: "text", text: " plain" },
  ]);
});

test("Office character formatting covers headings lists quotes and exact table cells while excluding code", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character nested text", richParagraphDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0, 5); await applyCharacters(page, { size: 18, color: "blue" });
  await expect(officeEditor(page).locator('[data-office-font-size="18"]')).toHaveCount(6);
  await officeEditor(page).locator("td").first().click(); await page.locator("#table-select").selectOption("cell");
  await applyCharacters(page, { size: 24, color: "red" });
  await expectCharacterStyle(officeEditor(page).locator("td").first().locator("span"), 24, "red");
  await expectCharacterStyle(officeEditor(page).locator("td").last().locator("span"), 18, "blue");
  await expect(officeEditor(page).locator("pre span")).toHaveCount(0);
  await selectCharacters(page, 6, 0, 4); await expect(page.locator("#character-format")).toBeDisabled();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content[6]).toEqual(first.content.content[6]);
  expect(saved.content.content[1].content[0].marks).toContainEqual({ type: "bold" });
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
});

test("Office character format-only comparison takeover replacement and reuse preserve all attribute boundaries", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character saved versions", characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 0, 5); await applyCharacters(page, { size: 24, color: "purple" });
  const second = await saveOffice(page, { objectId: first.document.object_id });
  await openOfficeComparison(page); await loadOfficeComparison(page, first.document.object_id, first.version.version_id, second.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("1 geändert");
  await expect(page.locator("#compare-results")).toContainText("Schriftgröße: 24 pt; Textfarbe: Violett");
  await page.locator("#compare-restore").click();
  const third = await saveOffice(page, { objectId: first.document.object_id }); expect(third.content).toEqual(first.content);
  await page.locator("#find-toggle").click(); await page.locator("#find-query").fill("café 😀 Beta");
  await page.locator("#replace-query").fill("NEW"); await page.locator("#replace-all").click();
  await expect(page.locator("#find-message")).toContainText("1 Treffer ersetzt"); await page.locator("#find-close").click();
  const fourth = await saveOffice(page, { objectId: first.document.object_id });
  expect(fourth.content.content[0].content).toEqual([characterText("Alpha NEW"), characterText(" END", { fontSize: 12, textColor: "red" })]);
  await openReuse(page, fourth, "Character independent copy"); await submitReuse(page, fourth); await expectReuseDraft(page, "Character independent copy");
  const copied = await saveOffice(page); expect(copied.content).toEqual(fourth.content);
  expect(copied.document.object_id).not.toBe(first.document.object_id);
});

test("Office character history and reader boundaries remain closed and failed save retries exact attributes", async ({ page, context }) => {
  const first = await createParagraphFixture(page, "Character permission retry", characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 0, 5); await applyCharacters(page, { size: 24, color: "purple" });
  const writes = paragraphWrites(page, first.document.object_id);
  await saveOffice(page, { objectId: first.document.object_id, status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  await expect(page.locator("#character-format")).toBeDisabled();
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(writes).toHaveLength(2); expect(writes[0]).toEqual(writes[1]);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  await openPrintHistory(page, first.document.object_id, first.version.version_id);
  await expect(page.locator("#character-format")).toBeDisabled();
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  try {
    await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
    await openOfficeDocument(reader, first.document.object_id); await expect(reader.locator("#character-format")).toBeDisabled();
    await expectCharacterStyle(officeEditor(reader).locator("span").first(), 24, "purple");
  } finally { await reader.close(); }
  expect((await officeContent(page, first.document.object_id)).content).toEqual(second.content);
});

test("Office character byte limits and context changes cannot alter or leak a pending selection", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character limits", { type: "doc", content: Array.from({ length: 620 }, () => paragraph("界".repeat(90))) });
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0, 619); await openCharacters(page);
  await page.locator("#character-size").selectOption("48"); await page.locator("#character-color").selectOption("purple");
  await page.locator("#character-apply").click(); await expect(page.locator("#character-status")).toContainText("überschreitet");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(officeEditor(page).locator("span")).toHaveCount(0);
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await expect(page.locator("#character-dialog")).toBeHidden(); await expect(page.locator("#office-editor")).toHaveText("");
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
});

test("Office fresh write revocation closes pending character choices and keeps the unsaved draft", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character write revocation", characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 0, 5); await applyCharacters(page, { size: 24, color: "purple" });
  await openCharacters(page); await page.locator("#character-size").selectOption("36");
  const features = await officeFeatures(page);
  try {
    await setOfficeFeatures(page, { ...features, "office_documents.documents.write": false });
    const response = page.waitForResponse((value) => new URL(value.url()).pathname === officeContentPath(first.document.object_id));
    // Model an external refresh arriving while the modal has pending choices.
    await page.locator("#documents-refresh").evaluate((button) => button.click());
    expect((await (await response).json()).can_write).toBe(false);
    await expect(page.locator("#character-dialog")).toBeHidden();
    await expect(page.locator("#character-format")).toBeDisabled();
    await expect(page.locator("#document-save")).toBeDisabled();
    await expectCharacterStyle(officeEditor(page).locator("span").first(), 24, "purple");
    expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
  } finally { await setOfficeFeatures(page, features); }
});

test("Office character edits undo separately from typing and coexist with heading shortcuts and inline code", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character keyboard", { type: "doc", content: [paragraph("Alpha")] });
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectCharacters(page, 0, 5); await page.keyboard.type(" BEFORE");
  await selectCharacters(page, 0, 0, 5); await applyCharacters(page, { size: 18, color: "blue" });
  await selectCharacters(page, 0, 12); await page.keyboard.type(" AFTER");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page)).toHaveText("Alpha BEFORE");
  await expectCharacterStyle(officeEditor(page).locator("span"), 18, "blue");
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator("span")).toHaveCount(0);
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page)).toHaveText("Alpha");
  await expect(page.locator("#document-save")).toBeDisabled();
  await selectCharacters(page, 0, 0, 5); await applyCharacters(page, { size: 18, color: "blue" });
  await officeEditor(page).press("Control+Alt+2"); await expectCharacterStyle(officeEditor(page).locator("h2 span"), 18, "blue");
  await page.locator('[data-command="code"]').click();
  await expect(officeEditor(page).locator("code")).toHaveText("Alpha");
  await expect(officeEditor(page).locator("span")).toHaveCount(0);
  await expect(page.locator("#character-format")).toBeDisabled();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content[0].content[0].marks).toEqual([{ type: "code" }]);
});

test("Office prints exact saved character sizes and colors in a real multipage PDF", async ({ page }) => {
  const first = await createParagraphFixture(page, "Character PDF", { type: "doc", content: [
    { type: "heading", attrs: { level: 2 }, content: [characterText("CHARACTER_PDF_HEAD", { fontSize: 28, textColor: "purple" })] },
    ...Array.from({ length: 24 }, (_, index) => ({ type: "paragraph", content: [characterText(`CHARACTER_${String(index).padStart(2, "0")} Café. ${"Saved size and color. ".repeat(3)}`, { fontSize: index % 2 ? 12 : 18, textColor: index % 2 ? "red" : "blue" })] })),
    { type: "paragraph", content: [characterText("CHARACTER_PDF_LAST", { fontSize: 18, textColor: "green" })] },
  ] });
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  const calls = await installPrintProbe(page, { pdfName: "office-character-a4-portrait.pdf" });
  await page.exposeFunction("measureCharacterPrint", async () => {
    await page.emulateMedia({ media: "print" });
    return page.locator("#office-print-root h2 span").evaluate((element) => ({ size: parseFloat(getComputedStyle(element).fontSize), color: getComputedStyle(element).color }));
  });
  await page.evaluate(() => { const print = window.print; window.print = async () => { window.characterPrintStyle = await window.measureCharacterPrint(); return print(); }; });
  await openPrintPreview(page, first.document.object_id, first.version.version_id);
  await expectCharacterStyle(page.locator("#print-preview h2 span"), 28, "purple");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-character-print-preview.png`, fullPage: true });
  await submitOfficePrint(page, first.document.object_id, first.version.version_id);
  await expect.poll(() => calls[0]?.pdf?.length || 0).toBeGreaterThan(1000);
  expectPdfStructure(calls[0].pdf, ["H1", "H2", "P"]);
  expect(pdfPageCount(calls[0].pdf, 594.96, 841.92)).toBeGreaterThan(1);
  const style = await page.evaluate(() => window.characterPrintStyle);
  expect(style.size).toBeCloseTo(28 * 4 / 3, 1); expect(style.color).toBe("rgb(126, 34, 206)");
  expect(calls[0].snapshot.text).toContain("CHARACTER_PDF_LAST"); expect(calls[0].snapshot.unsafeElements).toBe(0);
  await expectPrintCleared(page); expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});
