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

  const input = cell(page, 1, 1).locator("p"); await input.click(); await input.press("Home");
  await input.press("Shift+End"); await page.keyboard.type("7");
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
