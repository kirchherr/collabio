import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

test("Office category direction, label rotation and interval persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Category axis presentation proof", { text: "Canonical data remains ordered" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Reverse quarterly categories");
  await page.locator("#chart-alt").fill("Quarterly values shown in reverse order with diagonal alternating labels.");
  await page.locator("#chart-category-direction").selectOption("reverse");
  await page.locator("#chart-category-label-rotation").selectOption("diagonal");
  await page.locator("#chart-category-label-interval").selectOption("2");
  const preview = page.locator("#chart-preview .office-chart");
  await expect(preview).toHaveAttribute("data-category-label-rotation", "diagonal");
  await expect(preview.locator(".office-chart-categories span")).toHaveText(["Q4", "", "Q2", ""]);
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), chartAttrs = saved.content.content.find((entry) => entry.type === "chart").attrs;
  expect(chartAttrs.categoryAxisPresentation).toEqual({ direction: "reverse", labelRotation: "diagonal", labelInterval: 2 });
  expect(chartAttrs.categories).toEqual(["Q1", "Q2", "Q3", "Q4"]);
  expect(chartAttrs.series[0].values).toEqual([120, 140, 160, 180]);
  await openOfficeDocument(page, saved.document.object_id);
  const chart = officeEditor(page).locator(".office-chart");
  await expect(chart.locator(".office-chart-categories span")).toHaveText(["Q4", "", "Q2", ""]);
  await expect(chart).toHaveAttribute("aria-label", /Kategorien umgekehrt, Beschriftung diagonal, Intervall 2/);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-category-axis-${testInfo.project.name}.png`, fullPage: true });
});
