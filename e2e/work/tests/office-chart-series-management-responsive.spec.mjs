import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office series visibility and display order persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Series management proof", { text: "Canonical series stay in source order" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Managed quarterly series");
  await page.locator("#chart-alt").fill("Forecast and actual remain visible while plan stays in the saved source.");
  await page.locator("#chart-data").fill(
    "Kategorie\tPlan\tIst\tPrognose\nQ1\t120\t110\t130\nQ2\t140\t152\t155\nQ3\t160\t171\t175\nQ4\t180\t176\t190",
  );
  const manager = page.locator("#chart-series-management");
  await expect(manager.locator(".chart-series-management-row")).toHaveCount(3);
  await manager.getByRole("button", { name: "Prognose früher darstellen" }).click();
  await manager.getByRole("button", { name: "Prognose früher darstellen" }).click();
  await manager.getByRole("checkbox", { name: "Plan anzeigen" }).uncheck();
  await page.locator("#chart-data-table-visible").check();
  const preview = page.locator("#chart-preview .office-chart");
  await expect(preview).toHaveAttribute("data-visible-series", "2");
  await expect(preview.locator(".office-chart-legend span")).toHaveText(["Prognose", "Ist"]);
  await expect(preview.locator(".office-chart-data-visible thead th")).toHaveText(["Kategorie", "Prognose", "Ist"]);
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), chartAttrs = saved.content.content.find((entry) => entry.type === "chart").attrs;
  expect(chartAttrs.seriesManagement).toEqual({ order: [2, 0, 1], hidden: [0] });
  expect(chartAttrs.series.map((entry) => entry.name)).toEqual(["Plan", "Ist", "Prognose"]);
  expect(chartAttrs.series[0].values).toEqual([120, 140, 160, 180]);
  await openOfficeDocument(page, saved.document.object_id);
  const chart = officeEditor(page).locator(".office-chart");
  await expect(chart).toHaveAttribute("data-visible-series", "2");
  await expect(chart.locator(".office-chart-legend span")).toHaveText(["Prognose", "Ist"]);
  await expect(chart.locator(".office-chart-data-visible thead th")).toHaveText(["Kategorie", "Prognose", "Ist"]);
  await expect(chart).toHaveAttribute("aria-label", /2 von 3 Datenreihen sichtbar, Reihenfolge Prognose, Ist/);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-series-management-${testInfo.project.name}.png`, fullPage: true });
});
