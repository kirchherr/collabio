import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { newOfficeDraft, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

async function pasteTable(page, text) {
  await officeEditor(page).evaluate((editor, value) => {
    const clipboardData = new DataTransfer(); clipboardData.setData("text/plain", value);
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office reference lines and richer data labels persist responsively", async ({ page }, testInfo) => {
  test.setTimeout(85_000); await openOffice(page);
  await newOfficeDraft(page, "Chart analytics proof", { text: "Bounded analytical chart presentation" });
  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await pasteTable(page, "Quarter\tRevenue\nQ1\t120\nQ2\t155\nQ3\t185");
  const table = officeEditor(page).locator("table").first(); await table.locator("td").first().click();
  await page.locator("#table-caption").click(); await page.locator("#table-caption-text").fill("Revenue source");
  await page.locator("#table-caption-apply").click();

  await officeEditor(page).press("Control+End"); await officeEditor(page).press("Enter");
  await page.locator("#chart-options").click(); await page.locator("#chart-kind").selectOption("line");
  await page.locator("#chart-name").fill("Revenue with analytical lines");
  await page.locator("#chart-alt").fill("Quarterly revenue with target and floor reference lines.");
  await page.locator("#chart-linked").check(); await expect(page.locator("#chart-source-range")).toHaveValue("A1:B4");
  await page.locator("#chart-data-labels").check(); await page.locator("#chart-data-label-content").selectOption("category-value");
  await page.locator("#chart-data-label-position").selectOption("top");
  await page.locator("#chart-reference-add").click();
  const references = page.locator("#chart-reference-lines .chart-reference-row"); await expect(references).toHaveCount(1);
  await references.nth(0).locator('[data-field="label"]').fill("Target");
  await references.nth(0).locator('[data-field="value"]').fill("170");
  await page.locator("#chart-reference-add").click(); await expect(references).toHaveCount(2);
  await references.nth(1).locator('[data-field="label"]').fill("Floor");
  await references.nth(1).locator('[data-field="value"]').fill("110");
  await references.nth(1).locator('[data-field="color"]').selectOption("purple");
  await references.nth(1).locator('[data-field="lineStyle"]').selectOption("solid");
  await expect(page.locator("#chart-preview .office-chart-reference-lines span")).toHaveCount(2);
  await expect(page.locator('#chart-preview .office-chart-value-labels[data-position="top"] span')).toHaveCount(3);
  await page.locator("#chart-apply").click();

  const saved = await saveOffice(page), stored = saved.content.content.filter((entry) => entry.type === "chart");
  expect(stored).toHaveLength(1); expect(stored[0].attrs.dataLabelPresentation).toEqual({ content: "category-value", position: "top" });
  expect(stored[0].attrs.referenceLines).toEqual([
    { label: "Target", value: 170, color: "orange", lineStyle: "dashed" },
    { label: "Floor", value: 110, color: "purple", lineStyle: "solid" },
  ]);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page).locator(".office-chart-reference-lines span")).toHaveCount(2);
  await expect(officeEditor(page).locator('.office-chart-value-labels[data-position="top"] span')).toHaveCount(3);
  const geometry = await officeEditor(page).evaluate((editor) => ({ width: editor.scrollWidth,
    overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(geometry.overflow).toBeLessThanOrEqual(0); expect(geometry.width).toBeGreaterThan(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-chart-analytics-${testInfo.project.name}.png`, fullPage: true });
});
