import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, newOfficeDraft, officeContent, officeEditor,
  officeVersions, openOffice, openOfficeDocument, saveOffice, setOfficeAcl,
} from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row = 0, column = 0) => table(page).locator("tr").nth(row).locator("th,td").nth(column);

async function insertTable(page, { rows = 2, columns = 2, header = true } = {}) {
  await page.locator("#insert-menu").selectOption("insertTableCustom");
  await expect(page.locator("#table-insert-dialog")).toBeVisible();
  await page.locator("#table-rows").fill(String(rows));
  await page.locator("#table-columns").fill(String(columns));
  await page.locator("#table-with-header").setChecked(header);
  await page.locator("#table-insert-submit").click();
  await expect(page.locator("#table-insert-dialog")).toBeHidden();
  await expect(table(page)).toBeVisible();
}

async function shape(page, rows, columns) {
  await expect(table(page).locator("tr")).toHaveCount(rows);
  expect(await table(page).locator("tr").evaluateAll((entries) => entries.map((entry) => entry.querySelectorAll("th,td").length)))
    .toEqual(Array(rows).fill(columns));
}

async function populatedTable(page, title) {
  await newOfficeDraft(page, title, { text: "Table introduction" });
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await insertTable(page);
  for (const [row, column, text] of [[0, 0, "Alpha"], [0, 1, "Beta"], [1, 0, "Gamma"], [1, 1, "Delta"]]) {
    await cell(page, row, column).click();
    await page.keyboard.type(text);
  }
}

async function expectTableControlsDisabled(page) {
  for (const id of ["table-row-action", "table-column-action", "table-header-toggle", "table-delete"]) {
    await expect(page.locator(`#${id}`)).toBeDisabled();
  }
  await expect(page.locator("#insert-menu")).toBeDisabled();
}

test("Office configurable tables preserve content and marks through row, column and header edits and real versions", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await populatedTable(page, "Synthetic structural table editing");
  await cell(page).click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Shift+End");
  await page.locator('[data-command="bold"]').click();
  const first = await saveOffice(page);
  await cell(page, 1, 0).click();
  await page.locator("#table-row-action").selectOption("addRowBefore");
  await shape(page, 3, 2);
  await cell(page, 2, 0).click();
  await page.locator("#table-row-action").selectOption("addRowAfter");
  await shape(page, 4, 2);
  await cell(page, 0, 1).click();
  await page.locator("#table-column-action").selectOption("addColumnBefore");
  await shape(page, 4, 3);
  await cell(page, 0, 2).click();
  await page.locator("#table-column-action").selectOption("addColumnAfter");
  await shape(page, 4, 4);
  await page.locator("#table-header-toggle").click();
  await expect(table(page).locator("tr").first().locator("th")).toHaveCount(0);
  await page.locator("#table-header-toggle").click();
  await expect(table(page).locator("tr").first().locator("th")).toHaveCount(4);
  await expect(table(page).locator("strong")).toHaveText("Alpha");
  for (const text of ["Alpha", "Beta", "Gamma", "Delta"]) await expect(table(page)).toContainText(text);
  await cell(page, 1, 1).click();
  await page.locator("#table-select").selectOption("row");
  await expect(table(page).locator(".selectedCell")).toHaveCount(4);
  await page.locator("#table-select").selectOption("column");
  await expect(table(page).locator(".selectedCell")).toHaveCount(4);
  await page.locator("#table-select").selectOption("table");
  await expect(table(page).locator(".selectedCell")).toHaveCount(16);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(second.version.previous_version_id).toBe(first.version.version_id);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await shape(page, 4, 4);
  await expect(table(page).locator("strong")).toHaveText("Alpha");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  verifyBrowser();
});

test("Office table actions retain immediate editor focus and undo separately from adjacent typing", async ({ page }) => {
  await openOffice(page);
  await populatedTable(page, "Synthetic table action undo");
  const first = await saveOffice(page);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await cell(page).click();
  await page.keyboard.press("End");
  await page.keyboard.type(" before");
  await page.evaluate(() => {
    window.tableActionFocused = false;
    document.querySelector("#table-row-action").addEventListener("change", () => {
      window.tableActionFocused = document.activeElement === document.querySelector("#office-editor .tiptap");
    });
  });
  await page.locator("#table-row-action").selectOption("addRowAfter");
  expect(await page.evaluate(() => window.tableActionFocused)).toBe(true);
  await page.keyboard.type("after");
  await shape(page, 3, 2);
  await expect(table(page)).toContainText("after");
  await officeEditor(page).press("Control+z");
  await shape(page, 3, 2);
  await expect(table(page)).not.toContainText("after");
  await expect(table(page)).toContainText("Alpha before");
  await officeEditor(page).press("Control+z");
  await shape(page, 2, 2);
  await expect(table(page)).toContainText("Alpha before");
  await officeEditor(page).press("Control+z");
  await expect(table(page)).not.toContainText("before");
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  await expect(table(page)).toContainText("Alpha before");
  await officeEditor(page).press("Control+Shift+z");
  await shape(page, 3, 2);
  await officeEditor(page).press("Control+Shift+z");
  await expect(table(page)).toContainText("after");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office populated row, column and table removal require confirmation and remain undoable", async ({ page }) => {
  await openOffice(page);
  await populatedTable(page, "Synthetic confirmed table removal");
  const first = await saveOffice(page);
  for (const kind of ["row", "column", "table"]) {
    await cell(page).click();
    if (kind === "table") await page.locator("#table-select").selectOption("table");
    const remove = async () => {
      if (kind === "table") await page.keyboard.press("Delete");
      else await page.locator(`#table-${kind}-action`).selectOption(kind === "row" ? "deleteRow" : "deleteColumn");
    };
    await remove();
    await expect(page.locator("#table-remove-dialog")).toBeVisible();
    await shape(page, 2, 2);
    await page.locator("#table-remove-cancel").click();
    await expect(page.locator("#table-remove-dialog")).toBeHidden();
    await shape(page, 2, 2);
    await expect(table(page)).toContainText("Alpha");
    await remove();
    await page.locator("#table-remove-confirm").click();
    await expect(page.locator("#table-remove-dialog")).toBeHidden();
    if (kind === "table") await expect(table(page)).toHaveCount(0);
    else await shape(page, kind === "row" ? 1 : 2, kind === "column" ? 1 : 2);
    await page.locator('[data-command="undo"]').click();
    await shape(page, 2, 2);
    for (const text of ["Alpha", "Beta", "Gamma", "Delta"]) await expect(table(page)).toContainText(text);
  }
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office table editing stays unavailable to ordinary readers and historical views", async ({ page, context }) => {
  await openOffice(page);
  await populatedTable(page, "Synthetic table reader");
  const first = await saveOffice(page);
  await cell(page, 1, 1).click();
  await page.keyboard.press("End");
  await page.keyboard.type(" current");
  await saveOffice(page, { objectId: first.document.object_id });
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id);
  await cell(reader).click();
  await expectTableControlsDisabled(reader);
  await expect(officeEditor(reader)).toHaveAttribute("contenteditable", "false");
  await shape(reader, 2, 2);
  await page.locator("#history-tab").click();
  await page.locator(`[data-version-id="${first.version.version_id}"]`).click();
  await cell(page).click();
  await expectTableControlsDisabled(page);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  await expect(table(page)).not.toContainText("current");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office disables table mutations during a pending save and an uncertain storage failure until retry", async ({ page }) => {
  await openOffice(page);
  await populatedTable(page, "Synthetic pending table save");
  const first = await saveOffice(page);
  await cell(page).click();
  await page.locator("#table-row-action").selectOption("addRowAfter");
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let release;
  let started;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${path}`, async (route) => {
    started();
    await gate;
    await route.continue({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" } });
  }, { times: 1 });
  try {
    await page.locator("#document-save").click();
    await page.locator("#save-confirm").check();
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click();
    await ready;
    await expectTableControlsDisabled(page);
    await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
    release();
    const response = await failed;
    expect(response.status()).toBe(503);
    expect((await response.json()).detail).toBe("Office storage unavailable");
    await expect(page.locator("#save-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expectTableControlsDisabled(page);
    await shape(page, 3, 2);
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
    const retried = await saveOffice(page, { objectId: first.document.object_id });
    expect(retried.version.previous_version_id).toBe(first.version.version_id);
    await cell(page).click();
    await expect(page.locator("#table-row-action")).toBeEnabled();
    await shape(page, 3, 2);
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  } finally { release(); }
});

test("Office context change cancels a pending populated-table removal without changing its saved source", async ({ page }) => {
  await openOffice(page);
  await populatedTable(page, "Synthetic table context");
  const first = await saveOffice(page);
  await cell(page).click();
  await page.locator("#table-delete").click();
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  // Native dialog makes background controls inert; invoke the real context submit path.
  await page.evaluate((objectId) => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#readable-object-ids").value = objectId;
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }, first.document.object_id);
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#table-remove-dialog")).toBeHidden();
  await expect(page.locator("#office-editor")).toHaveText("");
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator(`[data-document-id="${first.document.object_id}"]`)).toHaveCount(0);
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office insertion cancellation and invalid dimensions stay clean and Tab cannot exceed the final table row", async ({ page }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic bounded table insertion", { text: "Boundary original" });
  const first = await saveOffice(page);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  for (const [rows, columns] of [[201, 2], [2, 21]]) {
    await page.locator("#insert-menu").selectOption("insertTableCustom");
    await page.locator("#table-rows").fill(String(rows));
    await page.locator("#table-columns").fill(String(columns));
    await page.locator("#table-insert-submit").click();
    await expect(page.locator("#table-insert-dialog")).toBeVisible();
    await expect(table(page)).toHaveCount(0);
    await page.locator("#table-insert-cancel").click();
    await expect(page.locator("#table-insert-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toBeDisabled();
    await expect(page.locator('[data-command="undo"]')).toBeDisabled();
    await expect(officeEditor(page)).toHaveText("Boundary original");
  }
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await insertTable(page, { rows: 1, columns: 2, header: false });
  await cell(page).click();
  await page.keyboard.press("Tab");
  await expect(page.locator("#table-info")).toContainText("Zelle 1, 2");
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#table-info")).toContainText("Zelle 1, 1");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await shape(page, 2, 2);
  await expect(page.locator("#table-info")).toContainText("Zelle 2, 1");
  await page.keyboard.type("New row typing");
  await expect(table(page)).toContainText("New row typing");
  await officeEditor(page).press("Control+z");
  await shape(page, 2, 2);
  await expect(table(page)).not.toContainText("New row typing");
  await officeEditor(page).press("Control+z");
  await shape(page, 1, 2);
  await officeEditor(page).press("Control+Shift+z");
  await shape(page, 2, 2);
  await officeEditor(page).press("Control+z");
  await shape(page, 1, 2);
  await officeEditor(page).press("Control+z");
  await expect(table(page)).toHaveCount(0);
  await insertTable(page, { rows: 200, columns: 1, header: false });
  await shape(page, 200, 1);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await cell(page, 199, 0).click();
  await page.keyboard.press("Tab");
  await shape(page, 200, 1);
  await expect(page.locator("#table-message")).toContainText("höchstens 200 Zeilen und 20 Spalten");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  expect((await officeContent(page, first.document.object_id)).content).toEqual(second.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office rejects a table expansion beyond the total canonical byte limit despite valid row and column counts", async ({ page }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic table byte boundary", { text: "界".repeat(66200) });
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await insertTable(page, { rows: 1, columns: 20, header: false });
  const first = await saveOffice(page);
  // Canonical JSON escapes non-ASCII code units; ordering does not change byte length.
  const canonicalBytes = JSON.stringify(first.content).replace(/[^\x00-\x7f]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`).length;
  expect(canonicalBytes).toBeGreaterThan(398000);
  expect(canonicalBytes).toBeLessThanOrEqual(400000);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await cell(page).click();
  await expect(page.locator('#table-row-action option[value="deleteRow"]')).toBeDisabled();
  await page.locator("#table-column-action").selectOption("addColumnAfter");
  await expect(page.locator("#table-message")).toContainText("höchstens 200 Zeilen und 20 Spalten");
  await shape(page, 1, 20);
  await page.locator("#table-row-action").selectOption("addRowAfter");
  await expect(page.locator("#table-message")).toContainText("überschreitet die unterstützte Dokumentgröße oder Struktur");
  await shape(page, 1, 20);
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});
