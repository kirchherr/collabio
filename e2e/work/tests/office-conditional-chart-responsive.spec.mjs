import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office conditional calculations, formats and row-linked charts persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000); await openOffice(page);
  await newOfficeDraft(page, "Conditional chart proof", { text: "Conditional quarterly analysis" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Series\tQ1\tQ2\tQ3\nKeys\t1\t2\t1\nValues\t10\t20\t30\nResult\t0\t0\t0");
  const table = officeEditor(page).locator("table").first();
  await table.locator("tr").nth(3).locator("td").nth(1).click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Quarterly rows");
  await page.locator("#table-caption-apply").click();

  const result = table.locator("tr").nth(3).locator("td").nth(1); await result.click();
  await page.locator("#table-formula").click();
  await page.locator("#table-formula-source").fill("=SUMMEWENN(B2:D2;1;B3:D3)");
  await page.locator("#table-formula-apply").click(); await expect(result).toHaveText("40");
  await result.click(); await page.locator("#table-cell-style").click();
  await page.locator("#table-cell-number-format").selectOption("currency-eur");
  await page.locator("#table-cell-style-apply").click();
  await expect(result).toHaveAttribute("data-office-number-format", "currency-eur");
  await expect(result).toHaveAttribute("data-office-display-value", "40,00 €");

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-name").fill("Quarterly row comparison");
  await page.locator("#chart-alt").fill("Keys and values for three quarters, sourced by rows.");
  await page.locator("#chart-linked").check(); await page.locator("#chart-source-orientation").selectOption("rows");
  await expect(page.locator("#chart-source-range")).toHaveValue("A1:D3");
  await page.locator("#chart-data-labels").check();
  await expect(page.locator("#chart-data")).toHaveValue("Kategorie\tKeys\tValues\nQ1\t1\t10\nQ2\t2\t20\nQ3\t1\t30");
  await page.locator("#chart-apply").click();
  const chart = officeEditor(page).locator("[data-office-chart]"); await expect(chart).toHaveCount(1);
  await expect(chart.locator(".office-chart-value-labels span")).toHaveCount(6);
  await chart.locator("xpath=..").locator(".office-chart-edit").click();
  await page.locator("#chart-kind").selectOption("line"); await page.locator("#chart-name").fill("Quarterly row trend");
  await page.locator("#chart-apply").click(); await expect(chart).toHaveAttribute("data-chart-kind", "line");

  const saved = await saveOffice(page);
  const storedTable = saved.content.content.find((entry) => entry.type === "table");
  expect(storedTable.content[3].content[1].attrs).toMatchObject({
    formula: "=SUMIF(B2:D2,1,B3:D3)", formulaResult: "40", numberFormat: "currency-eur",
  });
  const storedChart = saved.content.content.find((entry) => entry.type === "chart");
  expect(storedChart.attrs).toMatchObject({ kind: "line", title: "Quarterly row trend", dataLabels: true,
    source: { range: "A1:D3", orientation: "rows" } });
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator("[data-office-chart] .office-chart-value-labels span")).toHaveCount(6);
  await expect(officeEditor(page).locator("table tr").nth(3).locator("td").nth(1))
    .toHaveAttribute("data-office-display-value", "40,00 €");
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth, viewport: innerWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-conditional-chart-${testInfo.project.name}.png`, fullPage: true });
});
