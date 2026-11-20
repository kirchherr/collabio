import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office combo and scatter charts preserve bounded series presentation responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Scatter combo proof", { text: "Bounded per-series chart presentation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Point\tX value\tRevenue\tCost\nP1\t10\t120\t80\nP2\t20\t165\t105\nP3\t35\t210\t140");
  const table = officeEditor(page).locator("table").first(); await table.locator("td").first().click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Scatter and combo source");
  await page.locator("#table-caption-apply").click();

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("combo");
  await page.locator("#chart-name").fill("Revenue and cost combination");
  await page.locator("#chart-alt").fill("Revenue as bars with cost and X values as styled lines.");
  await page.locator("#chart-linked").check(); await page.locator("#chart-source-range").fill("A1:D4");
  const rows = page.locator("#chart-series-presentation .chart-series-presentation-row"); await expect(rows).toHaveCount(3);
  await rows.nth(1).locator('[data-field="marker"]').selectOption("square");
  await rows.nth(1).locator('[data-field="lineStyle"]').selectOption("dashed");
  await page.locator("#chart-palette").selectOption("accessible"); await page.locator("#chart-data-labels").check();
  await expect(page.locator("#chart-preview .office-chart-combo rect:not(.office-chart-marker)")).toHaveCount(3);
  await expect(page.locator("#chart-preview .office-chart-combo polyline")).toHaveCount(2);
  await page.locator("#chart-apply").click();

  const charts = officeEditor(page).locator("[data-office-chart]"); await expect(charts).toHaveCount(1);
  const chart = charts.first(); await expect(chart).toHaveAttribute("data-chart-kind", "combo");
  await chart.locator("xpath=..").locator(".office-chart-edit").click();
  await page.locator("#chart-kind").selectOption("scatter"); await page.locator("#chart-source-range").fill("A1:D4");
  await page.locator("#chart-name").fill("Revenue and cost scatter");
  await page.locator("#chart-alt").fill("Revenue and cost plotted against bounded numeric X values.");
  await expect(rows).toHaveCount(2); await rows.nth(0).locator('[data-field="marker"]').selectOption("diamond");
  await rows.nth(0).locator('[data-field="lineStyle"]').selectOption("dashed");
  await expect(page.locator("#chart-preview .office-chart-scatter .office-chart-marker")).toHaveCount(6);
  await expect(page.locator("#chart-preview .office-chart-scatter polyline")).toHaveCount(1);
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), stored = saved.content.content.filter((entry) => entry.type === "chart");
  expect(stored).toHaveLength(1); expect(stored[0].attrs.kind).toBe("scatter");
  expect(stored[0].attrs.seriesPresentation).toEqual([
    { renderAs: "points", marker: "diamond", lineStyle: "dashed" },
    { renderAs: "points", marker: "circle", lineStyle: "none" },
  ]);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator('[data-chart-kind="scatter"] .office-chart-marker')).toHaveCount(6);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-scatter-combo-${testInfo.project.name}.png`, fullPage: true });
});
