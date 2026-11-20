import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, newOfficeDraft, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const charts = (page) => officeEditor(page).locator("[data-office-chart]");

async function pasteTable(page, html, text) {
  await officeEditor(page).evaluate((editor, payload) => {
    const clipboardData = new DataTransfer();
    clipboardData.setData("text/html", payload.html); clipboardData.setData("text/plain", payload.text);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, { html, text });
}

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

test("Office linked charts recalculate from numbered formula tables and preserve versions responsively", async ({ page }, testInfo) => {
  test.setTimeout(75_000);
  await openOffice(page);
  await newOfficeDraft(page, "Linked calculation chart proof", { text: "Quarterly analysis" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page,
    `<table><tr><th>Quarter</th><th>Plan</th><th>Actual</th></tr>
      <tr><td>Q1</td><td>1.5</td><td>2.25</td></tr>
      <tr><td>Q2</td><td>3</td><td data-formula="=ROUND(B3*1.25,2)">3.75</td></tr></table>`,
    "Quarter\tPlan\tActual\nQ1\t1.5\t2.25\nQ2\t3\t3.75");
  const table = officeEditor(page).locator("table").first();
  await table.locator("td").first().click(); await page.locator("#table-caption").click();
  await page.locator("#table-caption-text").fill("Quarterly values"); await page.locator("#table-caption-apply").click();
  await expect(table.locator("caption")).toHaveText("Tabelle 1: Quarterly values");

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-name").fill("Quarterly comparison");
  await page.locator("#chart-alt").fill("Plan and actual values calculated from the quarterly table.");
  await page.locator("#chart-linked").check();
  await expect(page.locator("#chart-source-table")).toHaveValue(/table-[a-f0-9]{24}/);
  await expect(page.locator("#chart-source-range")).toHaveValue("A1:C3");
  await expect(page.locator("#chart-data")).toHaveValue("Kategorie\tPlan\tActual\nQ1\t1.5\t2.25\nQ2\t3\t3.75");
  await page.locator("#chart-apply").click(); await expect(charts(page)).toHaveCount(1);
  await expect(charts(page)).toHaveAttribute("aria-label", /verknüpft mit A1:C3/);
  const first = await saveOffice(page);

  const plan = table.locator("tr").nth(2).locator("td").nth(1).locator("p"); await plan.click();
  await plan.evaluate((paragraph) => { const selection = window.getSelection(), range = document.createRange();
    range.selectNodeContents(paragraph); selection.removeAllRanges(); selection.addRange(range); });
  await page.keyboard.type("4");
  await expect(table.locator("tr").nth(2).locator("td").nth(2)).toHaveText("5");
  await expect(charts(page).locator(".office-chart-data tbody tr").nth(1).locator("th,td")).toHaveText(["Q2", "4", "5"]);
  const geometry = await charts(page).evaluate((element) => ({ right: element.getBoundingClientRect().right,
    viewport: innerWidth, overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewport + 1); expect(geometry.overflow).toBeLessThanOrEqual(0);

  const second = await saveOffice(page, { objectId: first.document.object_id });
  const original = await officeContent(page, first.document.object_id, { versionId: first.version.version_id });
  expect(original.content.content.find((entry) => entry.type === "chart").attrs.series[0].values).toEqual([1.5, 3]);
  expect(second.content.content.find((entry) => entry.type === "chart").attrs.series).toMatchObject([
    { name: "Plan", values: [1.5, 4] }, { name: "Actual", values: [2.25, 5] },
  ]);
  await openOfficeDocument(page, first.document.object_id);
  await expect(charts(page).locator(".office-chart-data tbody tr").nth(1).locator("th,td")).toHaveText(["Q2", "4", "5"]);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-linked-chart-${testInfo.project.name}.png`, fullPage: true });
});
