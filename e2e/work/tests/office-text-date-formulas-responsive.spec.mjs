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

test("Office text and calendar formulas persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000); await openOffice(page);
  await newOfficeDraft(page, "Text and calendar formula proof", { text: "Deterministic labels and dates" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Name\tCode\tLabel\tMonth end\tWeekday\nAlpha\t2026\t0\t0\t0\nBeta\t2027\t0\t0\t0");
  const table = officeEditor(page).locator("table").first();
  await setFormula(page, table.locator("tr").nth(1).locator("td").nth(2),
    '=VERKETTEN(LINKS(A2;4);" / ";RECHTS(B2;2))', "Alph / 26");
  await setFormula(page, table.locator("tr").nth(2).locator("td").nth(2),
    '=XVERWEIS("Beta";A2:A3;B2:B3)', "2027");
  await setFormula(page, table.locator("tr").nth(1).locator("td").nth(3),
    "=TAG(EDATUM(DATUM(2024;1;31);1))", "29");
  await setFormula(page, table.locator("tr").nth(1).locator("td").nth(4),
    "=WOCHENTAG(DATUM(2026;10;13))", "2");

  const saved = await saveOffice(page), stored = saved.content.content.find((entry) => entry.type === "table");
  expect(stored.content[1].content[2].attrs).toMatchObject({
    formula: '=CONCAT(LEFT(A2,4)," / ",RIGHT(B2,2))', formulaResult: "Alph / 26",
  });
  expect(stored.content[2].content[2].attrs).toMatchObject({
    formula: '=XLOOKUP("Beta",A2:A3,B2:B3)', formulaResult: "2027",
  });
  await openOfficeDocument(page, saved.document.object_id);
  const reloaded = officeEditor(page).locator("table").first();
  await expect(reloaded.locator("tr").nth(1).locator("td").nth(2)).toHaveText("Alph / 26");
  await expect(reloaded.locator("tr").nth(1).locator("td").nth(3)).toHaveText("29");
  await expect(reloaded.locator("tr").nth(1).locator("td").nth(4)).toHaveText("2");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-text-date-formulas-${testInfo.project.name}.png`, fullPage: true });
});
