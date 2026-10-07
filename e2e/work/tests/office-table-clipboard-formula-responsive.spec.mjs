import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const table = (page) => officeEditor(page).locator("table").first();
const cell = (page, row, column) => table(page).locator("tr").nth(row).locator("th,td").nth(column);
const matrix = (page) => table(page).locator("tr").evaluateAll((rows) => rows.map((row) =>
  [...row.querySelectorAll("th,td")].map((entry) => entry.textContent.trim())));

async function pasteTable(page, html, text) {
  await officeEditor(page).evaluate((editor, payload) => {
    const clipboardData = new DataTransfer();
    clipboardData.setData("text/html", payload.html); clipboardData.setData("text/plain", payload.text);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, { html, text });
}

test("Office imports safe Word Excel tables and evaluates local formulas responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Clipboard formula proof", { text: "Imported table follows" });
  const baseline = await saveOffice(page);
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  const html = `<table><thead><tr><th>Item</th><th>Q1</th><th>Q2</th><th>Total</th></tr></thead><tbody>
    <tr><td style="background-color:#d9eaf7"><strong>Alpha</strong><img src="https://clipboard.invalid/leak"></td><td>2</td><td>3</td><td data-formula="=SUM(B2:C2)">5</td></tr>
    <tr><td>Bravo<script>leak()</script></td><td>4</td><td>6</td><td>10</td></tr></tbody></table>`;
  await pasteTable(page, html, "Item\tQ1\tQ2\tTotal\nAlpha\t2\t3\t5\nBravo\t4\t6\t10");
  expect(await matrix(page)).toEqual([
    ["Item", "Q1", "Q2", "Total"], ["Alpha", "2", "3", "5"], ["Bravo", "4", "6", "10"],
  ]);
  await expect(officeEditor(page).locator('img[src*="clipboard.invalid"],script')).toHaveCount(0);
  await expect(cell(page, 1, 0)).toHaveAttribute("data-office-cell-fill", "blue");
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B2:C2)");

  const input = cell(page, 1, 1).locator("p"); await input.click();
  await input.evaluate((paragraph) => {
    const selection = window.getSelection(), range = document.createRange(); range.selectNodeContents(paragraph);
    selection.removeAllRanges(); selection.addRange(range);
  });
  await page.keyboard.type("7"); await expect(cell(page, 1, 1)).toHaveText("7");
  await expect(cell(page, 1, 3)).toHaveText("10");
  await page.locator('[data-command="undo"]').click(); await expect(cell(page, 1, 1)).toHaveText("2");
  await expect(cell(page, 1, 3)).toHaveText("5"); await page.locator('[data-command="redo"]').click();
  await expect(cell(page, 1, 3)).toHaveText("10");

  await cell(page, 2, 3).click(); await page.locator("#table-formula").click();
  await page.locator("#table-formula-source").fill("=MAX(B2:C3)");
  await page.locator("#table-formula-apply").click(); await expect(cell(page, 2, 3)).toHaveText("7");
  await page.locator('[data-command="undo"]').click(); await expect(cell(page, 2, 3)).toHaveText("10");
  await page.locator('[data-command="redo"]').click(); await expect(cell(page, 2, 3)).toHaveText("7");

  const saved = await saveOffice(page, { objectId: baseline.document.object_id });
  expect((await officeContent(page, baseline.document.object_id, { versionId: baseline.version.version_id })).content)
    .toEqual(baseline.content);
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content[1].content[3].attrs).toMatchObject({ formula: "=SUM(B2:C2)", formulaResult: "10" });
  expect(savedTable.content[2].content[3].attrs).toMatchObject({ formula: "=MAX(B2:C3)", formulaResult: "7" });
  await openOfficeDocument(page, baseline.document.object_id);
  expect(await matrix(page)).toEqual([
    ["Item", "Q1", "Q2", "Total"], ["Alpha", "7", "3", "10"], ["Bravo", "4", "6", "7"],
  ]);
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview table tr")).toHaveCount(3);
  await expect(page.locator('#print-preview td[data-office-cell-formula="=MAX(B2:C3)"]')).toHaveText("7");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-clipboard-formula-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
  expect(saved.version.previous_version_id).toBe(baseline.version.version_id);
});

test("Office pastes formatted Excel cells into an existing table and expands it atomically", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Clipboard range proof", { text: "Existing table follows" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page,
    "<table><tr><th>Name</th><th>Q1</th><th>Q2</th><th>Total</th></tr><tr><td>Existing</td><td>1</td><td>1</td><td>2</td></tr></table>",
    "Name\tQ1\tQ2\tTotal\nExisting\t1\t1\t2");
  await cell(page, 1, 0).click();
  await pasteTable(page,
    `<table><tr><td style="background-color:#e2f0d9"><strong><em>Alpha</em></strong></td><td>2</td><td>3</td><td data-formula="=SUM(B1:C1)">5</td></tr>
      <tr><td><u>Bravo</u><iframe src="https://clipboard.invalid/leak"></iframe></td><td>4</td><td>6</td><td data-formula="=SUM(B2:C2)">10</td></tr></table>`,
    "Alpha\t2\t3\t5\nBravo\t4\t6\t10");
  expect(await matrix(page)).toEqual([
    ["Name", "Q1", "Q2", "Total"], ["Alpha", "2", "3", "5"], ["Bravo", "4", "6", "10"],
  ]);
  await expect(cell(page, 1, 0)).toHaveAttribute("data-office-cell-fill", "green");
  await expect(cell(page, 1, 0).locator("strong em")).toHaveText("Alpha");
  await expect(cell(page, 2, 0).locator("u")).toHaveText("Bravo");
  await expect(officeEditor(page).locator('iframe[src*="clipboard.invalid"]')).toHaveCount(0);
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B2:C2)");
  await expect(cell(page, 2, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B3:C3)");
  await page.locator('[data-command="undo"]').click();
  expect(await matrix(page)).toEqual([["Name", "Q1", "Q2", "Total"], ["Existing", "1", "1", "2"]]);
  await page.locator('[data-command="redo"]').click(); await expect(cell(page, 2, 3)).toHaveText("10");
  const saved = await saveOffice(page);
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content).toHaveLength(3);
  expect(savedTable.content[2].content[3].attrs).toMatchObject({ formula: "=SUM(B3:C3)", formulaResult: "10" });
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-range-paste-${testInfo.project.name}.png`, fullPage: true });
});

test("Office formulas follow column insertion row duplication and deleted references", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Structural formula proof", { text: "Formula table follows" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page,
    `<table><tr><th>Name</th><th>Q1</th><th>Q2</th><th>Total</th></tr>
      <tr><td>Alpha</td><td>2</td><td>3</td><td data-formula="=SUM(B2:C2)">5</td></tr>
      <tr><td>Bravo</td><td>4</td><td>6</td><td data-formula="=SUM(B3:C3)">10</td></tr></table>`,
    "Name\tQ1\tQ2\tTotal\nAlpha\t2\t3\t5\nBravo\t4\t6\t10");

  await cell(page, 1, 1).click(); await page.locator("#table-column-action").selectOption("addColumnBefore");
  await expect(table(page).locator("tr").first().locator("th,td")).toHaveCount(5);
  await expect(cell(page, 1, 4)).toHaveAttribute("data-office-cell-formula", "=SUM(C2:D2)");
  await expect(cell(page, 2, 4)).toHaveAttribute("data-office-cell-formula", "=SUM(C3:D3)");
  await page.locator('[data-command="undo"]').click(); await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B2:C2)");
  await page.locator('[data-command="redo"]').click(); await expect(cell(page, 1, 4)).toHaveText("5");

  await cell(page, 1, 1).click(); await page.locator("#table-column-action").selectOption("deleteColumn");
  await page.locator("#table-remove-confirm").click();
  await expect(table(page).locator("tr").first().locator("th,td")).toHaveCount(4);
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B2:C2)");

  await cell(page, 1, 0).click(); await page.locator("#table-select").selectOption("row");
  await page.locator("#table-row-action").selectOption("duplicateRows");
  await expect(table(page).locator("tr")).toHaveCount(4);
  await expect(cell(page, 2, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B3:C3)");
  await expect(cell(page, 3, 3)).toHaveAttribute("data-office-cell-formula", "=SUM(B4:C4)");

  await cell(page, 1, 1).click(); await page.locator("#table-column-action").selectOption("deleteColumn");
  await page.locator("#table-remove-confirm").click();
  await expect(cell(page, 1, 2)).toHaveAttribute("data-office-cell-formula", "=SUM(#BEZUG!:B2)");
  await expect(cell(page, 1, 2)).toHaveText("#BEZUG!");
  const saved = await saveOffice(page);
  const savedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(savedTable.content[2].content[2].attrs).toMatchObject({ formula: "=SUM(#BEZUG!:B3)", formulaResult: "#BEZUG!" });
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-formula-structure-${testInfo.project.name}.png`, fullPage: true });
});

test("Office absolute and mixed formulas copy and restructure by anchor axis", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Anchored formula proof", { text: "Anchored formulas follow" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page,
    `<table><tr><th>Name</th><th>Q1</th><th>Q2</th><th>Total</th></tr>
      <tr><td>Alpha</td><td>2</td><td>3</td><td data-formula="=SUM($B$2:C2)">5</td></tr>
      <tr><td>Bravo</td><td>4</td><td>6</td><td data-formula="=SUM($B3:C$3)">10</td></tr></table>`,
    "Name\tQ1\tQ2\tTotal\nAlpha\t2\t3\t5\nBravo\t4\t6\t10");
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B$2:C2)");
  await cell(page, 1, 3).click(); await page.locator("#table-formula").click();
  await page.locator("#table-formula-source").fill("=SUM($B$2;C2)");
  await page.locator("#table-formula-apply").click();
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B$2,C2)");

  await cell(page, 1, 1).click(); await page.locator("#table-column-action").selectOption("addColumnBefore");
  await expect(cell(page, 1, 4)).toHaveAttribute("data-office-cell-formula", "=SUM($C$2,D2)");
  await expect(cell(page, 2, 4)).toHaveAttribute("data-office-cell-formula", "=SUM($C3,D$3)");
  await page.locator('[data-command="undo"]').click();
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B$2,C2)");
  await page.locator('[data-command="redo"]').click(); await expect(cell(page, 1, 4)).toHaveText("5");
  await cell(page, 1, 1).click(); await page.locator("#table-column-action").selectOption("deleteColumn");
  await page.locator("#table-remove-confirm").click();

  await cell(page, 1, 0).click(); await page.locator("#table-select").selectOption("row");
  await page.locator("#table-row-action").selectOption("duplicateRows");
  await expect(cell(page, 1, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B$2,C2)");
  await expect(cell(page, 2, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B$2,C3)");
  await expect(cell(page, 3, 3)).toHaveAttribute("data-office-cell-formula", "=SUM($B4,C$4)");
  const saved = await saveOffice(page);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(cell(page, 2, 3)).toHaveText("5");
  await page.locator("#document-print").click();
  await expect(page.locator('#print-preview td[data-office-cell-formula="=SUM($B$2,C3)"]')).toHaveText("5");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-table-formula-anchors-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
