import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office chart axes and presentation persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000); await openOffice(page);
  await newOfficeDraft(page, "Chart axis proof", { text: "Quarterly revenue presentation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Quarter\tRevenue\tCost\nQ1\t120\t90\nQ2\t140\t100\nQ3\t160\t130");
  const table = officeEditor(page).locator("table").first(); await table.locator("td").first().click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Quarterly finance");
  await page.locator("#table-caption-apply").click();

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Revenue and cost by quarter");
  await page.locator("#chart-alt").fill("Revenue and cost rise from Q1 through Q3 on a fixed euro scale.");
  await page.locator("#chart-linked").check(); await expect(page.locator("#chart-source-range")).toHaveValue("A1:C4");
  await page.locator("#chart-category-axis-title").fill("Quarter");
  await page.locator("#chart-value-axis-title").fill("Euro");
  await page.locator("#chart-number-format").selectOption("currency-eur");
  await page.locator("#chart-axis-mode").selectOption("manual");
  await page.locator("#chart-axis-minimum").fill("0"); await page.locator("#chart-axis-maximum").fill("200");
  await page.locator("#chart-axis-major-unit").fill("50"); await page.locator("#chart-legend-position").selectOption("right");
  await page.locator("#chart-data-labels").check();
  await expect(page.locator("#chart-preview .office-chart-axis-ticks span")).toHaveCount(5);
  await expect(page.locator("#chart-preview .office-chart-gridlines i")).toHaveCount(5);
  await expect(page.locator("#chart-preview .office-chart")).toHaveAttribute("data-legend-position", "right");
  await page.locator("#chart-apply").click();

  const chart = officeEditor(page).locator("[data-office-chart]"); await expect(chart).toHaveCount(1);
  await expect(chart.locator(".office-chart-category-axis-title")).toHaveText("Quarter");
  await expect(chart.locator(".office-chart-value-axis-title")).toHaveText("Euro");
  await expect(chart.locator(".office-chart-value-labels span")).toHaveCount(6);
  await chart.locator("xpath=..").locator(".office-chart-edit").click();
  await expect(page.locator("#chart-axis-mode")).toHaveValue("manual");
  await expect(page.locator("#chart-axis-maximum")).toHaveValue("200");
  await page.locator("#chart-legend-position").selectOption("top"); await page.locator("#chart-apply").click();
  await expect(chart).toHaveAttribute("data-legend-position", "top");

  const saved = await saveOffice(page), stored = saved.content.content.find((entry) => entry.type === "chart");
  expect(stored.attrs).toMatchObject({ kind: "line", legendPosition: "top", dataLabels: true,
    axes: { mode: "manual", categoryTitle: "Quarter", valueTitle: "Euro", minimum: 0, maximum: 200,
      majorUnit: 50, gridlines: true, numberFormat: "currency-eur" },
    source: { range: "A1:C4", orientation: "columns" } });
  await openOfficeDocument(page, saved.document.object_id);
  const reloaded = officeEditor(page).locator("[data-office-chart]");
  await expect(reloaded).toHaveAttribute("data-legend-position", "top");
  await expect(reloaded.locator(".office-chart-axis-ticks span")).toHaveCount(5);
  await expect(reloaded.locator(".office-chart-gridlines i")).toHaveCount(5);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-axis-${testInfo.project.name}.png`, fullPage: true });
});
