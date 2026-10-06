import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const charts = (page) => officeEditor(page).locator("[data-office-chart]");

test("Office charts edit duplicate order save reload and print responsively", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await openOffice(page);
  const baseline = await createOfficeDocument(page, "Native chart proof", "Text before chart");
  const editor = officeEditor(page), objectId = baseline.document.object_id;
  await editor.locator("p").click(); await page.locator("#chart-options").click();
  await expect(page.locator("#chart-dialog")).toBeVisible();
  await page.locator("#chart-name").fill("Quarterly plan");
  await page.locator("#chart-alt").fill("Plan and actual values rise across four quarters.");
  await page.locator("#chart-data").fill("Kategorie\tPlan\tIst\nQ1\t120\t110\nQ2\t140\t152\nQ3\t160\t171\nQ4\t180\t176");
  await expect(page.locator("#chart-preview .office-chart-bar")).toHaveCount(8);
  await page.locator("#chart-apply").click(); await expect(charts(page)).toHaveCount(1);
  await expect(charts(page)).toHaveAttribute("data-chart-kind", "bar");
  await expect(charts(page).locator(".office-chart-data tbody tr")).toHaveCount(4);
  const geometry = await charts(page).evaluate((element) => ({ right: element.getBoundingClientRect().right,
    viewport: innerWidth, overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewport + 1); expect(geometry.overflow).toBeLessThanOrEqual(0);
  await page.locator('[data-command="undo"]').click(); await expect(charts(page)).toHaveCount(0);
  await page.locator('[data-command="redo"]').click(); await expect(charts(page)).toHaveCount(1);

  await officeEditor(page).locator(".office-chart-edit").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-apply").click(); await expect(charts(page)).toHaveAttribute("data-chart-kind", "line");
  await expect(charts(page).locator("polyline")).toHaveCount(2);
  await officeEditor(page).locator(".office-chart-edit").click(); await page.locator("#chart-duplicate").click();
  await expect(charts(page)).toHaveCount(2);
  const ids = await charts(page).evaluateAll((elements) => elements.map((element) => element.dataset.officeChart));
  expect(new Set(ids).size).toBe(2);
  await charts(page).nth(1).locator("xpath=..").locator(".office-chart-edit").click();
  await expect(page.locator("#chart-previous")).toBeEnabled(); await page.locator("#chart-previous").click();
  await charts(page).first().locator("xpath=..").locator(".office-chart-edit").click(); await page.locator("#chart-remove").click();
  await expect(charts(page)).toHaveCount(1);

  await charts(page).locator("xpath=..").locator(".office-chart-edit").click();
  await page.locator("#chart-kind").selectOption("pie");
  await page.locator("#chart-data").fill("Kategorie\tAnteil\nQ1\t10\nQ2\t20\nQ3\t30\nQ4\t40");
  await expect(page.locator("#chart-apply")).toBeEnabled(); await page.locator("#chart-apply").click();
  await expect(charts(page)).toHaveAttribute("data-chart-kind", "pie");
  const saved = await saveOffice(page, { objectId });
  const savedChart = saved.content.content.find((entry) => entry.type === "chart");
  expect(savedChart.attrs).toMatchObject({ kind: "pie", title: "Quarterly plan", legend: true,
    categories: ["Q1", "Q2", "Q3", "Q4"], series: [{ name: "Anteil", color: "teal", values: [10, 20, 30, 40] }] });
  expect((await officeContent(page, objectId, { versionId: baseline.version.version_id })).content).toEqual(baseline.content);
  await openOfficeDocument(page, objectId); await expect(charts(page)).toHaveAttribute("data-chart-kind", "pie");
  await page.locator("#document-print").click(); await expect(page.locator("#print-preview .office-print-chart")).toHaveCount(1);
  await expect(page.locator("#print-preview .office-chart-pie")).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();
});
