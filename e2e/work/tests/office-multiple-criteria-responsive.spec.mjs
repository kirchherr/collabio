import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

async function setFormula(page, cell, formula, result) {
  await cell.click(); await page.locator("#table-formula").click();
  await page.locator("#table-formula-source").fill(formula); await page.locator("#table-formula-apply").click();
  await expect(cell).toHaveText(result);
}

test("Office multiple-criteria formulas persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000); await openOffice(page);
  await newOfficeDraft(page, "Multiple criteria proof", { text: "Regional quarterly analysis" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Region\tQuarter\tValue\tResult\n1\t1\t10\t0\n1\t2\t20\t0\n2\t1\t30\t0\n1\t1\t40\t0");
  const table = officeEditor(page).locator("table").first();
  await setFormula(page, table.locator("tr").nth(1).locator("td").nth(3),
    "=SUMMEWENNS(C2:C5;A2:A5;1;B2:B5;1)", "50");
  await setFormula(page, table.locator("tr").nth(2).locator("td").nth(3),
    "=ZÄHLENWENNS(A2:A5;1;B2:B5;1)", "2");
  await setFormula(page, table.locator("tr").nth(3).locator("td").nth(3),
    "=MITTELWERTWENNS(C2:C5;A2:A5;1;B2:B5;1)", "25");

  const saved = await saveOffice(page), stored = saved.content.content.find((entry) => entry.type === "table");
  expect(stored.content.slice(1, 4).map((row) => row.content[3].attrs)).toEqual([
    expect.objectContaining({ formula: "=SUMIFS(C2:C5,A2:A5,1,B2:B5,1)", formulaResult: "50" }),
    expect.objectContaining({ formula: "=COUNTIFS(A2:A5,1,B2:B5,1)", formulaResult: "2" }),
    expect.objectContaining({ formula: "=AVERAGEIFS(C2:C5,A2:A5,1,B2:B5,1)", formulaResult: "25" }),
  ]);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator("table tr").nth(1).locator("td").nth(3)).toHaveText("50");
  await expect(officeEditor(page).locator("table tr").nth(2).locator("td").nth(3)).toHaveText("2");
  await expect(officeEditor(page).locator("table tr").nth(3).locator("td").nth(3)).toHaveText("25");
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-multiple-criteria-${testInfo.project.name}.png`, fullPage: true });
});
