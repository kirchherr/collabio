import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office richer chart types and presentation persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Chart types proof", { text: "Quarterly chart presentation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Quarter\tRevenue\tCost\nQ1\t120\t90\nQ2\t140\t100\nQ3\t160\t130");
  const table = officeEditor(page).locator("table").first(); await table.locator("td").first().click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Quarterly finance");
  await page.locator("#table-caption-apply").click();

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("stacked-bar");
  await page.locator("#chart-name").fill("Stacked quarterly totals");
  await page.locator("#chart-alt").fill("Revenue and cost stacked by quarter on a fixed scale.");
  await page.locator("#chart-linked").check(); await expect(page.locator("#chart-source-range")).toHaveValue("A1:C4");
  await page.locator("#chart-palette").selectOption("accessible"); await page.locator("#chart-style").selectOption("soft");
  await page.locator("#chart-title-alignment").selectOption("left"); await page.locator("#chart-data-labels").check();
  await page.locator("#chart-category-axis-title").fill("Quarter"); await page.locator("#chart-value-axis-title").fill("Total");
  await page.locator("#chart-axis-mode").selectOption("manual"); await page.locator("#chart-axis-minimum").fill("0");
  await page.locator("#chart-axis-maximum").fill("400"); await page.locator("#chart-axis-major-unit").fill("100");
  await expect(page.locator("#chart-preview .office-chart-bar-segment")).toHaveCount(6);
  await expect(page.locator("#chart-preview .office-chart")).toHaveAttribute("data-chart-style", "soft");
  await page.locator("#chart-apply").click();

  const charts = officeEditor(page).locator("[data-office-chart]"); await expect(charts).toHaveCount(1);
  const first = charts.first(); await expect(first).toHaveAttribute("data-chart-kind", "stacked-bar");
  await expect(first).toHaveAttribute("data-title-alignment", "left");
  await first.locator("xpath=..").locator(".office-chart-edit").click();
  await page.locator("#chart-kind").selectOption("area"); await page.locator("#chart-axis-mode").selectOption("auto");
  await page.locator("#chart-palette").selectOption("warm"); await page.locator("#chart-style").selectOption("focus");
  await page.locator("#chart-title-alignment").selectOption("right");
  await expect(page.locator("#chart-preview .office-chart-lines polygon")).toHaveCount(2);
  await page.locator("#chart-apply").click(); await expect(first).toHaveAttribute("data-chart-kind", "area");

  await first.locator("xpath=..").locator(".office-chart-edit").click();
  await page.locator("#chart-kind").selectOption("doughnut");
  await page.locator("#chart-name").fill("Revenue share by quarter");
  await page.locator("#chart-alt").fill("Quarterly revenue shown as a ring chart.");
  await expect(page.locator("#chart-linked")).toBeChecked(); await expect(page.locator("#chart-source-range")).toHaveValue("A1:B4");
  await page.locator("#chart-palette").selectOption("monochrome"); await page.locator("#chart-style").selectOption("soft");
  await page.locator("#chart-title-alignment").selectOption("center");
  await expect(page.locator("#chart-axis-fields")).toHaveAttribute("disabled", "");
  await expect(page.locator("#chart-axis-mode")).toBeDisabled();
  await expect(page.locator("#chart-preview .office-chart-doughnut")).toBeVisible();
  await page.locator("#chart-apply").click(); await expect(charts).toHaveCount(1);

  const saved = await saveOffice(page), stored = saved.content.content.filter((entry) => entry.type === "chart");
  expect(stored).toHaveLength(1); expect(stored[0].attrs.kind).toBe("doughnut");
  expect(stored[0].attrs.presentation).toEqual({ palette: "monochrome", style: "soft", titleAlignment: "center" });
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator('[data-chart-kind="doughnut"] .office-chart-doughnut')).toBeVisible();
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-types-${testInfo.project.name}.png`, fullPage: true });
});
