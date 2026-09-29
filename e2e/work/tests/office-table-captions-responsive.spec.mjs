import { test, expect } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import { OFFICE_HEADERS, officeEditor, openOffice, createOfficeDocument, saveOffice } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const cell = (text) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text)] });
const table = (text) => ({ type: "table", content: [{ type: "tableRow", content: [cell(text)] }] });

async function selectReferenceText(page) {
  const target = officeEditor(page).locator("p").first();
  await target.click(); await page.keyboard.press("Home");
  await page.keyboard.down("Shift"); await page.keyboard.press("End"); await page.keyboard.up("Shift");
}

async function captionTable(page, index, caption) {
  await officeEditor(page).locator("table").nth(index).locator("td").click();
  await page.locator("#table-caption").click();
  await expect(page.locator("#table-caption-dialog")).toBeVisible();
  await page.locator("#table-caption-text").fill(caption);
  await page.locator("#table-caption-apply").click();
  await expect(page.locator("#table-caption-dialog")).toBeHidden();
}

test("Office table captions renumber, preserve stable references and print semantic local links", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await openOffice(page);
  const first = await createOfficeDocument(page, "Table caption proof", "See details table");
  const fixture = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS,
    data: { title: first.version.title, document: { type: "doc", content: [paragraph("See details table"), table("Overview"), table("Details")] },
      mutation_reference: `table-caption-fixture-${first.version.version_id}`, expected_current_version_id: first.version.version_id,
      human_confirmation: true },
  });
  expect(fixture.status()).toBe(200); await page.locator("#document-reload").click();

  await captionTable(page, 0, "Overview"); await captionTable(page, 1, "Details");
  const captions = officeEditor(page).locator("table caption");
  await expect(captions).toHaveText(["Tabelle 1: Overview", "Tabelle 2: Details"]);
  const ids = await officeEditor(page).locator("table[data-office-table]").evaluateAll((entries) => entries.map((entry) => entry.dataset.officeTable));
  expect(new Set(ids).size).toBe(2);

  await captionTable(page, 0, "Overview revised");
  await expect(captions.first()).toHaveText("Tabelle 1: Overview revised");
  await officeEditor(page).press("Control+z"); await expect(captions.first()).toHaveText("Tabelle 1: Overview");
  await officeEditor(page).press("Control+Shift+z"); await expect(captions.first()).toHaveText("Tabelle 1: Overview revised");

  await selectReferenceText(page); await page.locator("#cross-reference-options").click();
  await page.locator("#cross-reference-target").selectOption(ids[1]); await page.locator("#cross-reference-apply").click();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.content[0].content[0].marks).toEqual([{ type: "crossReference", attrs: { targetId: ids[1] } }]);
  expect(saved.content.content.filter((entry) => entry.type === "table").map((entry) => entry.attrs.tableId)).toEqual(ids);

  const prints = await installPrintProbe(page, { pdfName: `office-table-captions-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const printed = page.locator(`#print-preview #office-table-${ids[1]}`);
  await expect(printed.locator("caption")).toHaveText("Tabelle 2: Details");
  await expect(page.locator("#print-preview a[data-office-cross-reference]")).toHaveAttribute("href", `#office-table-${ids[1]}`);
  await page.locator("#print-preview").screenshot({ path: `${ARTIFACT_DIR}/office-table-captions-${testInfo.project.name}.png` });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1); await expect.poll(() => prints[0].pdf).not.toBeNull();
  expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Link");
  await page.locator("#print-close").click();

  await officeEditor(page).locator("table").first().locator("td").click();
  await page.locator("#table-delete").click(); await page.locator("#table-remove-confirm").click();
  await expect(captions).toHaveText(["Tabelle 1: Details"]);
  await selectReferenceText(page); await page.locator("#cross-reference-options").click();
  await expect(page.locator("#cross-reference-jump")).toBeEnabled(); await page.locator("#cross-reference-cancel").click();
  await officeEditor(page).press("Control+z");
  await expect(captions).toHaveText(["Tabelle 1: Overview revised", "Tabelle 2: Details"]);

  await officeEditor(page).locator("table").nth(1).locator("td").click(); await page.locator("#table-caption").click();
  await page.locator("#table-caption-remove").click();
  await selectReferenceText(page); await page.locator("#cross-reference-options").click();
  await expect(page.locator('#cross-reference-target option[data-broken="true"]')).toHaveValue(ids[1]);
  await expect(page.locator("#cross-reference-jump")).toBeDisabled(); await page.locator("#cross-reference-cancel").click();
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page).locator(`table[data-office-table="${ids[1]}"] caption`)).toHaveText("Tabelle 2: Details");
});
