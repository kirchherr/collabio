import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office logarithmic primary and bounded secondary axes persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Advanced chart axes proof", { text: "Explicit dual-scale presentation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Plan and actual with dual axes");
  await page.locator("#chart-alt").fill("Plan on a logarithmic primary axis and actual on a linear secondary axis.");
  await page.locator("#chart-primary-scale").selectOption("logarithmic");
  await page.locator("#chart-secondary-enabled").check();
  await page.locator("#chart-secondary-series").selectOption({ label: "Ist" });
  await page.locator("#chart-secondary-title").fill("Ist-Werte");
  await page.locator("#chart-secondary-number-format").selectOption("decimal");
  await page.locator("#chart-trendline-enabled").check();
  await page.locator("#chart-trendline-series").selectOption({ label: "Ist" });
  await expect(page.locator("#chart-preview .office-chart-axis-frame")).toHaveAttribute("data-secondary-axis", "true");
  await expect(page.locator("#chart-preview .office-chart-secondary-axis-title")).toHaveText("Ist-Werte");
  await expect(page.locator("#chart-preview .office-chart-secondary-axis-ticks span")).toHaveCount(5);
  await expect(page.locator("#chart-preview .office-chart-trendline")).toHaveCount(1);
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), charts = saved.content.content.filter((entry) => entry.type === "chart");
  expect(charts).toHaveLength(1); expect(charts[0].attrs.axisOptions).toEqual({
    primaryScale: "logarithmic",
    secondary: { seriesIndex: 1, title: "Ist-Werte", scale: "linear", mode: "auto",
      minimum: null, maximum: null, majorUnit: null, numberFormat: "decimal" },
  });
  await openOfficeDocument(page, saved.document.object_id);
  const chart = officeEditor(page).locator(".office-chart");
  await expect(chart.locator(".office-chart-secondary-axis-title")).toHaveText("Ist-Werte");
  await expect(chart).toHaveAttribute("aria-label", /logarithmische Hauptachse · Sekundärachse Ist-Werte: Ist/);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-advanced-axes-${testInfo.project.name}.png`, fullPage: true });
});
