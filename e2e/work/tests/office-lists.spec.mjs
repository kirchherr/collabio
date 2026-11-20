import { expect, test } from "@playwright/test";
import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { OFFICE_PATH, OFFICE_READER_ID, officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument,
  saveOffice, setOfficeAcl, openOfficeComparison, loadOfficeComparison } from "./office-support.mjs";
import { paragraph, paragraphWrites, selectParagraphBlocks } from "./paragraph-helper.mjs";
import { selectCharacters, applyCharacters } from "./character-helper.mjs";
import { openPrintPreview } from "./office-print-support.mjs";
import { listFixture, listItem, listLevel, listStart, openListOptions, ordered } from "./list-helper.mjs";

test("Office indents selected list siblings with exact formatting undo and immutable confirmed versions", async ({ page }) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await listFixture(page);
  const original = await officeEditor(page).innerHTML();
  const writes = paragraphWrites(page, first.document.object_id);
  await selectParagraphBlocks(page, 2, 3);
  await listLevel(page, "indent");
  const top = officeEditor(page).locator(":scope > ol");
  await expect(top.locator(":scope > li")).toHaveCount(2);
  await expect(top.locator("ol > li")).toHaveCount(2);
  await expect(top.locator("ol span")).toHaveAttribute("data-office-text-color", "green");
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  expect(writes).toEqual([]);
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content[1].attrs).toEqual({ start: 7 });
  expect(next.content.content[1].content[0].content[1].content).toEqual(first.content.content[1].content.slice(1, 3));
  expect(next.content.content.slice(2)).toEqual(first.content.content.slice(2));
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  expect(writes).toHaveLength(1);
  verify();
});

test("Office lifts nested siblings and converts an outer item to a paragraph while preserving sublists", async ({ page }) => {
  const first = await listFixture(page);
  const original = await officeEditor(page).innerHTML();
  await selectParagraphBlocks(page, 2, 3); await listLevel(page, "indent");
  await selectParagraphBlocks(page, 2, 3); await listLevel(page, "outdent");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await selectCharacters(page, 5, 2); await listLevel(page, "outdent");
  await expect(officeEditor(page).locator(":scope > ul")).toHaveCount(0);
  await expect(officeEditor(page).locator(":scope > ol")).toHaveCount(2);
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content.slice(2, 4)).toEqual(first.content.content[2].content[0].content);
});

test("Office changes only the nearest ordered list start and preserves it in comparison and print", async ({ page }) => {
  const first = await listFixture(page);
  await selectCharacters(page, 6, 2); await listStart(page, 42);
  await expect(page.locator("#list-dialog")).toBeHidden();
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content[1]).toEqual(first.content.content[1]);
  expect(next.content.content[2].content[0].content[1].attrs).toEqual({ start: 42 });
  await openPrintPreview(page, first.document.object_id, next.version.version_id);
  await expect(page.locator("#print-preview ul ol")).toHaveAttribute("start", "42");
  await page.locator("#print-close").click();
  await openOfficeComparison(page);
  await loadOfficeComparison(page, first.document.object_id, first.version.version_id, next.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("42. Nested first");
  await expect(page.locator("#compare-results")).toContainText("20. Nested first");
});

test("Office list options keep cancellation invalid numbers and same-number no-op clean", async ({ page }) => {
  await listFixture(page);
  await selectCharacters(page, 1, 2); await openListOptions(page);
  await expect(page.locator("#list-indent")).toBeDisabled();
  await page.locator("#list-start").fill("99");
  await page.keyboard.press("Escape");
  await expect(page.locator("#document-save")).toBeDisabled();
  await listStart(page, 7);
  await expect(page.locator("#list-status")).toContainText("Keine Änderung");
  for (const invalid of ["0", "1000001", "1.5", "-1", "", "1e3"]) {
    await page.locator("#list-start").fill(invalid); await page.locator("#list-apply").click();
    await expect(page.locator("#list-status")).toContainText("ganze Startzahl");
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  await page.locator("#list-cancel").click();
  await selectCharacters(page, 5, 2); await openListOptions(page);
  await expect(page.locator("#list-numbering")).toBeHidden();
  await page.locator("#list-close").click();
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office list keyboard changes keep pending marks and independent undo while Tab in tables navigates cells", async ({ page }) => {
  await listFixture(page);
  const original = await officeEditor(page).innerHTML();
  await selectCharacters(page, 2, 0); await applyCharacters(page, { size: 24, color: "purple" });
  await officeEditor(page).press("Alt+Shift+ArrowRight");
  await page.keyboard.type("Added ");
  await expect(officeEditor(page).locator('span[data-office-text-color="purple"]')).toHaveText("Added ");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page).locator(":scope > ol ol")).toHaveCount(1);
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await selectCharacters(page, 2, 2); await officeEditor(page).press("Tab");
  await expect(officeEditor(page).locator(":scope > ol ol")).toHaveCount(1);
  await officeEditor(page).press("Shift+Tab");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await selectCharacters(page, 9, 2); await officeEditor(page).press("Tab");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  expect(await page.evaluate(() => window.getSelection().anchorNode.parentElement.closest("td")?.textContent)).toBe("Other cell");
  await selectCharacters(page, 9, 2); await officeEditor(page).press("Alt+Shift+ArrowRight");
  await expect(officeEditor(page).locator("td ol ol")).toHaveCount(1);
});

test("Office list options reject mixed lists plain text code and cell selections", async ({ page }) => {
  await listFixture(page);
  await selectCharacters(page, 0, 2); await expect(page.locator("#list-options")).toBeDisabled();
  await selectParagraphBlocks(page, 4, 5); await expect(page.locator("#list-options")).toBeDisabled();
  const original = await officeEditor(page).innerHTML();
  await officeEditor(page).press("Tab");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await officeEditor(page).locator("pre").click(); await expect(page.locator("#list-options")).toBeDisabled();
  await officeEditor(page).locator("td").first().click(); await page.locator("#table-select").selectOption("cell");
  await expect(page.locator("#list-options")).toBeDisabled();
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office list dialogs invalidate on context change and remain unavailable to readers and history", async ({ page, context }) => {
  const first = await listFixture(page);
  await selectCharacters(page, 1, 2); await listStart(page, 10);
  await saveOffice(page, { objectId: first.document.object_id });
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id);
  await selectCharacters(reader, 1, 2); await expect(reader.locator("#list-options")).toBeDisabled();
  await reader.keyboard.press("Alt+Shift+ArrowRight");
  await expect(reader.locator("#document-save")).toBeDisabled();
  await page.locator("#history-tab").click(); await page.locator(`[data-version-id="${first.version.version_id}"]`).click();
  await expect(page.locator("#list-options")).toBeDisabled();
  await page.locator("#document-reload").click(); await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await selectCharacters(page, 2, 2); await openListOptions(page);
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await expect(page.locator("#list-dialog")).toBeHidden();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office list indentation rejects excessive nesting without changing content or dirty state", async ({ page }) => {
  let nested = ordered(1, listItem(paragraph("Deep first")), listItem(paragraph("Deep second")));
  for (let level = 0; level < 14; level += 1) nested = ordered(1, listItem(paragraph(`Level ${level}`), nested));
  const first = await listFixture(page, { type: "doc", content: [nested] });
  const original = await officeEditor(page).innerHTML();
  await selectCharacters(page, 15, 2); await openListOptions(page); await page.locator("#list-indent").click();
  await expect(page.locator("#list-status")).toContainText("Verschachtelung");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office list controls stay closed during a save and uncertain failure until the confirmed retry", async ({ page }) => {
  const first = await listFixture(page);
  await selectCharacters(page, 2, 2); await listLevel(page, "indent");
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let release, started;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${path}`, async (route) => {
    started(); await gate;
    const response = await route.fetch({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" }, maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({ response });
  }, { times: 1 });
  try {
    await page.locator("#document-save").click(); await page.locator("#save-confirm").check();
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click(); await ready;
    await expect(page.locator("#list-options")).toBeDisabled();
    release(); expect((await failed).status()).toBe(503);
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expect(page.locator("#list-options")).toBeDisabled();
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
    await saveOffice(page, { objectId: first.document.object_id });
    await selectCharacters(page, 2, 2); await expect(page.locator("#list-options")).toBeEnabled();
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  } finally { release(); }
});

test("Office list numbering rejects canonical byte overflow before changing the draft", async ({ page }) => {
  const document = { type: "doc", content: [paragraph("Padding"), ordered(1, listItem(paragraph("Target")))] };
  const asciiBytes = (value) => JSON.stringify(value).replace(/[^\x00-\x7f]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`).length;
  document.content[0].content[0].text += "界".repeat(Math.floor((399998 - asciiBytes(document)) / 6));
  document.content[0].content[0].text += "a".repeat(399998 - asciiBytes(document));
  const first = await listFixture(page, document);
  const original = await officeEditor(page).innerHTML();
  await selectCharacters(page, 1, 2); await listStart(page, 1000000);
  await expect(page.locator("#list-status")).toContainText("Dokumentgröße");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});
