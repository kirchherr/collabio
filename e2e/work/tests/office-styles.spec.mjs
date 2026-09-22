import { expect, test } from "@playwright/test";
import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { OFFICE_PATH, OFFICE_READER_ID, officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument,
  saveOffice, setOfficeAcl, openOfficeComparison, loadOfficeComparison } from "./office-support.mjs";
import { applyParagraphFormat, paragraphWrites, selectParagraphBlocks } from "./paragraph-helper.mjs";
import { applyCharacters, expectCharacterStyle, selectCharacters } from "./character-helper.mjs";
import { installPrintProbe, openPrintPreview, expectPdfStructure, submitOfficePrint, expectPrintCleared } from "./office-print-support.mjs";
import { openReuse, submitReuse } from "./office-reuse-support.mjs";
import { applyStyle, openStyles, styleDefinition, styleDocument, styleFixture, styleValues } from "./style-helper.mjs";

test("Office creates a reusable named style for selected paragraphs with isolated undo and confirmed versions", async ({ page }) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await styleFixture(page, styleDocument({ linked: false }));
  const original = await officeEditor(page).innerHTML();
  const writes = paragraphWrites(page, first.document.object_id);
  await selectParagraphBlocks(page, 1, 2);
  await applyStyle(page, { choice: "new", values: { name: "Literal <b>style</b> 😀", fontSize: 24, textColor: "purple", textAlign: "right" } });
  await expectCharacterStyle(officeEditor(page).locator("p").nth(0), 24, "purple");
  await expect(officeEditor(page).locator("strong")).toHaveText("First paragraph");
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  expect(writes).toEqual([]);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.attrs.styles).toHaveLength(1);
  expect(saved.content.attrs.styles[0].name).toBe("Literal <b>style</b> 😀");
  expect(saved.content.content[1].attrs.styleId).toBe(saved.content.content[2].attrs.styleId);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  expect(writes).toHaveLength(1);
  verify();
});

test("Office updates all style-bound blocks without changing text structures direct overrides or older versions", async ({ page }) => {
  const content = styleDocument(); content.content[2].attrs.textAlign = "right";
  content.content[2].content[0].marks = [{ type: "textStyle", attrs: { fontSize: 12, textColor: "red" } }];
  const first = await styleFixture(page, content);
  await selectCharacters(page, 1, 2);
  await applyStyle(page, { values: { fontSize: 24, textColor: "purple", textAlign: "left", name: "Shared body" }, update: true });
  for (const element of await officeEditor(page).locator("[data-office-style-id]").all()) await expectCharacterStyle(element, 24, "purple");
  await expect(officeEditor(page).locator("p").nth(1)).toHaveCSS("text-align", "right");
  await expectCharacterStyle(officeEditor(page).locator("p").nth(1).locator("span"), 12, "red");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content).toEqual(first.content.content);
  expect(saved.content.attrs.styles[0].character).toEqual({ fontSize: 24, textColor: "purple" });
  await page.locator("#document-reload").click();
  await expectCharacterStyle(officeEditor(page).locator("h2"), 24, "purple");
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
});

test("Office style updates retain pending typing marks and are undone separately from text", async ({ page }) => {
  await styleFixture(page);
  await selectCharacters(page, 1, 0); await applyCharacters(page, { size: 12, color: "red" });
  await applyStyle(page, { values: { fontSize: 24 }, update: true });
  await page.keyboard.type("Added ");
  await expectCharacterStyle(officeEditor(page).locator('span[data-office-text-color="red"]'), 12, "red");
  await officeEditor(page).press("Control+z");
  await expectCharacterStyle(officeEditor(page).locator("h2"), 24, "blue");
  await officeEditor(page).press("Control+z");
  await expectCharacterStyle(officeEditor(page).locator("h2"), 18, "blue");
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office named styles survive heading list split and selected table cell transformations", async ({ page }) => {
  const first = await styleFixture(page);
  await selectCharacters(page, 1, 3); await page.locator("#text-style").selectOption("heading-3");
  await expect(officeEditor(page).locator("h3")).toHaveAttribute("data-office-style-id", "body");
  await page.locator('[data-command="bulletList"]').click();
  await expect(officeEditor(page).locator("ul").first().locator("p")).toHaveAttribute("data-office-style-id", "body");
  await selectCharacters(page, 2, 6); await officeEditor(page).press("Enter");
  await expect(officeEditor(page).locator('[data-office-style-id="body"]')).toHaveCount(7);
  await officeEditor(page).locator("td").first().click(); await page.locator("#table-select").selectOption("cell");
  await applyStyle(page, { choice: "preset:title", values: { name: "Cell title" } });
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.attrs.styles).toHaveLength(2);
  expect(saved.content.content.at(-1)).toEqual(first.content.content.at(-1));
});

test("Office named style cancellation invalid duplicate names no-op and removal remain predictable", async ({ page }) => {
  await styleFixture(page);
  await selectCharacters(page, 1, 2); await openStyles(page);
  await styleValues(page, { fontSize: 24 }); await page.keyboard.press("Escape");
  await expect(page.locator("#document-save")).toBeDisabled();
  await openStyles(page); await page.locator("#style-update").click();
  await expect(page.locator("#style-status")).toContainText("Keine Änderung");
  await page.locator("#style-choice").selectOption("new");
  for (const name of ["", "Fließtext", "x".repeat(61)]) {
    await page.locator("#style-name").fill(name); await page.locator("#style-apply").click();
    await expect(page.locator("#style-status")).toContainText("eindeutigen Namen");
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  await page.locator("#style-cancel").click(); await openStyles(page); await page.locator("#style-remove").click();
  await expect(officeEditor(page).locator("p").first()).not.toHaveAttribute("data-office-style-id");
  await officeEditor(page).press("Control+z"); await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office named style limits reject a new catalog entry and excessive bytes before mutating the draft", async ({ page }) => {
  const content = styleDocument();
  content.attrs.styles.push(...Array.from({ length: 19 }, (_, n) => ({ ...styleDefinition(), id: `style-${n}`, name: `Style ${n}` })));
  await styleFixture(page, content); await selectCharacters(page, 1, 2); await openStyles(page);
  await page.locator("#style-choice").selectOption("new"); await expect(page.locator("#style-apply")).toBeDisabled();
  await expect(page.locator("#style-status")).toContainText("20 Vorlagen");
  await page.locator("#style-close").click();
  const large = styleDocument();
  const bytes = (value) => JSON.stringify(value).replace(/[^\x00-\x7f]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`).length;
  large.content[2].content[0].text += "界".repeat(Math.floor((399980 - bytes(large)) / 6));
  large.content[2].content[0].text += "a".repeat(399980 - bytes(large));
  await styleFixture(page, large); const original = await officeEditor(page).innerHTML();
  await selectCharacters(page, 1, 2); await openStyles(page); await page.locator("#style-name").fill("界".repeat(60));
  await page.locator("#style-update").click(); await expect(page.locator("#style-status")).toContainText("Dokumentgrößenlimits");
  expect(await officeEditor(page).innerHTML()).toBe(original); await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office named style controls respect readers history code and context invalidation", async ({ page, context }) => {
  const first = await styleFixture(page); await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id); await selectCharacters(reader, 1, 2);
  await expect(reader.locator("#style-options")).toBeDisabled(); await expectCharacterStyle(officeEditor(reader).locator("h2"), 18, "blue");
  await officeEditor(page).locator("pre").click(); await expect(page.locator("#style-options")).toBeDisabled();
  await selectCharacters(page, 1, 2); await applyStyle(page, { values: { fontSize: 24 }, update: true });
  await saveOffice(page, { objectId: first.document.object_id });
  await page.locator("#history-tab").click(); await page.locator(`[data-version-id="${first.version.version_id}"]`).click();
  await expect(page.locator("#style-options")).toBeDisabled(); await expectCharacterStyle(officeEditor(page).locator("h2"), 18, "blue");
  await page.locator("#document-reload").click(); await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await selectCharacters(page, 1, 2); await openStyles(page);
  await page.evaluate(() => { document.querySelector("#user-id").value = "work-assignee-e2e"; document.querySelector("#role-ids").value = "office-reader"; document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await expect(page.locator("#style-dialog")).toBeHidden(); await expect(page.locator("#style-preview")).toBeEmpty();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office named styles cannot change during pending or uncertain saves and survive confirmed retry", async ({ page }) => {
  const first = await styleFixture(page); await selectCharacters(page, 1, 2);
  await applyStyle(page, { values: { fontSize: 24 }, update: true });
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let release, started; const gate = new Promise((resolve) => { release = resolve; }); const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${path}`, async (route) => { started(); await gate; const response = await route.fetch({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" }, maxRetries: 0, maxRedirects: 0 }); await route.fulfill({ response }); }, { times: 1 });
  try {
    await page.locator("#document-save").click(); await page.locator("#save-confirm").check();
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click(); await ready; await expect(page.locator("#style-options")).toBeDisabled();
    release(); expect((await failed).status()).toBe(503);
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen"); await expect(page.locator("#style-options")).toBeDisabled();
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
    await saveOffice(page, { objectId: first.document.object_id }); await selectCharacters(page, 1, 2);
    await expect(page.locator("#style-options")).toBeEnabled();
  } finally { release(); }
});

test("Office styles survive literal replacement comparison print PDF and independent reuse", async ({ page }) => {
  const first = await styleFixture(page);
  await page.locator("#find-toggle").click(); await page.locator("#find-query").fill("paragraph"); await page.locator("#replace-query").fill("wording");
  await expect(page.locator("#replace-all")).toBeEnabled(); await page.locator("#replace-all").click(); await page.locator("#find-close").click();
  await selectCharacters(page, 1, 2); await applyStyle(page, { values: { fontSize: 24 }, update: true });
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  await openOfficeComparison(page); await loadOfficeComparison(page, first.document.object_id, first.version.version_id, saved.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("Schriftgröße: 24 pt"); await expect(page.locator("#compare-results")).toContainText("Formatvorlagen");
  await page.locator("#compare-close").click();
  const calls = await installPrintProbe(page, { pdfName: "office-styles-a4-portrait.pdf" });
  await openPrintPreview(page, first.document.object_id, saved.version.version_id);
  await expectCharacterStyle(page.locator("#print-preview h2"), 24, "blue");
  await submitOfficePrint(page, first.document.object_id, saved.version.version_id);
  await expect.poll(() => calls[0]?.pdf?.length || 0).toBeGreaterThan(1000);
  expectPdfStructure(calls[0].pdf, ["H1", "H2", "P"]); await expectPrintCleared(page);
  await openReuse(page, saved, "Independent styled copy"); await submitReuse(page, saved);
  const copied = await saveOffice(page); expect(copied.content).toEqual(saved.content); expect(copied.document.object_id).not.toBe(first.document.object_id);
  await selectCharacters(page, 1, 2); await applyStyle(page, { values: { fontSize: 32 }, update: true });
  await saveOffice(page, { objectId: copied.document.object_id });
  expect((await officeContent(page, first.document.object_id)).content).toEqual(saved.content);
});

test("Office direct paragraph overrides reset to the linked template and applying a template resets only paragraph values", async ({ page }) => {
  await styleFixture(page); await selectCharacters(page, 1, 2);
  await applyParagraphFormat(page, { textAlign: "right" }); await expect(officeEditor(page).locator("p").first()).toHaveCSS("text-align", "right");
  await applyParagraphFormat(page, { textAlign: "default" }); await expect(officeEditor(page).locator("p").first()).toHaveCSS("text-align", "center");
  await applyParagraphFormat(page, { spacingAfter: 24 }); await applyStyle(page);
  await expect(officeEditor(page).locator("p").first()).toHaveAttribute("data-office-spacing-after", "12");
  await expect(officeEditor(page).locator("strong")).toHaveText("First paragraph");
});
