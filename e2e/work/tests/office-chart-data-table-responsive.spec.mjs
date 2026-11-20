import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office visible chart data tables persist and support keyboard inspection", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Accessible chart data proof", { text: "Visible canonical chart values" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click();
  await page.locator("#chart-name").fill("Plan and actual data table");
  await page.locator("#chart-alt").fill("Quarterly plan and actual values with a visible data table.");
  await page.locator("#chart-data-table-visible").check();
  await page.locator("#chart-data-table-position").selectOption("above");
  const preview = page.locator("#chart-preview .office-chart");
  await expect(preview.locator(".office-chart-data-scroll")).toHaveAttribute("data-position", "above");
  await expect(preview.locator(".office-chart-data-help")).toHaveText(/Pfeiltasten navigieren oder horizontal wischen/);
  await expect(preview.locator(".office-chart-data-key")).toHaveCount(2);
  const cells = preview.locator(".office-chart-data th,.office-chart-data td");
  await cells.first().focus(); await page.keyboard.press("ArrowRight");
  await expect(cells.nth(1)).toBeFocused(); await page.keyboard.press("ArrowDown");
  await expect(cells.nth(4)).toBeFocused();
  await expect(cells.nth(4)).toHaveText("120");
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), charts = saved.content.content.filter((entry) => entry.type === "chart");
  expect(charts).toHaveLength(1);
  expect(charts[0].attrs.dataTablePresentation).toEqual({ position: "above", showLegendKeys: true });
  await openOfficeDocument(page, saved.document.object_id);
  const chart = officeEditor(page).locator(".office-chart");
  await expect(chart).toHaveAttribute("role", "group");
  await expect(chart).toHaveAttribute("aria-label", /sichtbare Datentabelle/);
  await expect(chart.locator(".office-chart-data tbody tr")).toHaveCount(4);
  await expect(chart.locator(".office-chart-data caption")).toHaveClass(/visually-hidden/);
  await expect(chart.locator(".office-chart-data")).toHaveAttribute("id", `${charts[0].attrs.id}-data`);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-data-table-${testInfo.project.name}.png`, fullPage: true });
});
