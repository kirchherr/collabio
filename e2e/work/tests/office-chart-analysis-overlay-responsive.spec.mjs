import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office trendlines and fixed error bars persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Chart overlay proof", { text: "Deterministic trend and uncertainty" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Revenue trend and uncertainty");
  await page.locator("#chart-alt").fill("Quarterly actual revenue with a trendline and fixed error bars.");
  await page.locator("#chart-trendline-enabled").check();
  await page.locator("#chart-trendline-series").selectOption({ label: "Ist" });
  await page.locator("#chart-trendline-color").selectOption("orange");
  await page.locator("#chart-error-bars-enabled").check();
  await page.locator("#chart-error-bars-series").selectOption({ label: "Ist" });
  await page.locator("#chart-error-bars-amount").fill("12");
  await page.locator("#chart-error-bars-color").selectOption("purple");
  await expect(page.locator("#chart-preview .office-chart-trendline")).toHaveCount(1);
  await expect(page.locator("#chart-preview .office-chart-error-bar")).toHaveCount(4);
  await expect(page.locator("#chart-status")).toContainText("Vorschau");
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), charts = saved.content.content.filter((entry) => entry.type === "chart");
  expect(charts).toHaveLength(1); expect(charts[0].attrs.analysis).toEqual({
    trendline: { seriesIndex: 1, color: "orange", lineStyle: "dashed" },
    errorBars: { seriesIndex: 1, amount: 12, color: "purple" },
  });
  await openOfficeDocument(page, saved.document.object_id);
  const chart = officeEditor(page).locator(".office-chart");
  await expect(chart.locator(".office-chart-trendline")).toHaveCount(1);
  await expect(chart.locator(".office-chart-error-bar")).toHaveCount(4);
  await expect(chart).toHaveAttribute("aria-label", /Trendlinie Ist · Fehlerbalken Ist: ±12/);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-analysis-overlay-${testInfo.project.name}.png`, fullPage: true });
});
