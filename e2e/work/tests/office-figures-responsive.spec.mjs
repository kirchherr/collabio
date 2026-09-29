import { test, expect } from "@playwright/test";
import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { createOfficeDocument, OFFICE_HEADERS, officeEditor, openOffice, saveOffice } from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });

async function pixels(page, color) {
  return Buffer.from(await page.evaluate((fill) => {
    const canvas = document.createElement("canvas"); canvas.width = 80; canvas.height = 60;
    const context = canvas.getContext("2d"); context.fillStyle = fill; context.fillRect(0, 0, 80, 60);
    return canvas.toDataURL("image/png").split(",")[1];
  }, color), "base64");
}

async function upload(page, objectId, color, caption) {
  const response = await page.request.post(`${BASE_URL}/v1/office/documents/${objectId}/images`, {
    data: await pixels(page, color), headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" },
  });
  expect(response.status()).toBe(200);
  return { ...(await response.json()).image, alt: `${caption} sample`, caption, decorative: false };
}

async function selectReferenceText(page) {
  await officeEditor(page).locator("p").first().selectText();
  await expect(page.locator("#cross-reference-options")).toBeEnabled();
}

async function selectImage(page, index) {
  const node = officeEditor(page).locator(".office-image-node").nth(index);
  if (!(await node.evaluate((element) => element.classList.contains("ProseMirror-selectednode")))) await node.click();
  await expect(node).toHaveClass(/ProseMirror-selectednode/);
  await expect(page.locator("#image-options")).toHaveText("Bild bearbeiten …");
}

test("Office figure captions renumber on reorder and remain stable cross-reference targets", async ({ page }, testInfo) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Figure numbering proof", "See first figure");
  const one = await upload(page, first.document.object_id, "#2563eb", "Overview");
  const two = await upload(page, first.document.object_id, "#f97316", "Details");
  const fixture = await page.request.post(`${BASE_URL}/v1/office/documents/${first.document.object_id}/versions`, {
    headers: OFFICE_HEADERS, data: { title: first.version.title, document: { type: "doc", content: [p("See first figure"),
      { type: "image", attrs: one }, { type: "image", attrs: two }] }, mutation_reference: `figure-fixture-${first.version.version_id}`,
    expected_current_version_id: first.version.version_id, human_confirmation: true },
  });
  expect(fixture.status()).toBe(200); await page.locator("#document-reload").click();
  const images = officeEditor(page).locator("img"); await expect(images).toHaveCount(2);
  for (const index of [0, 1]) {
    await selectImage(page, index); await page.locator("#image-options").click();
    await page.locator("#image-numbered").check(); await page.locator("#image-apply").click();
    await expect(officeEditor(page).locator("figure[data-office-figure]")).toHaveCount(index + 1);
    await selectImage(page, index); await page.locator("#image-options").click();
    await expect(page.locator("#image-numbered")).toBeChecked(); await page.locator("#image-cancel").click();
  }
  const captions = officeEditor(page).locator("figcaption");
  await expect(captions).toHaveText(["Abbildung 1: Overview", "Abbildung 2: Details"]);
  const ids = await officeEditor(page).locator("figure[data-office-figure]").evaluateAll((entries) => entries.map((entry) => entry.dataset.officeFigure));
  expect(new Set(ids).size).toBe(2);

  await selectImage(page, 1); await page.locator("#image-options").click(); await page.locator("#image-up").click();
  await expect(captions).toHaveText(["Abbildung 1: Details", "Abbildung 2: Overview"]);
  await officeEditor(page).press("Control+z"); await expect(captions).toHaveText(["Abbildung 1: Overview", "Abbildung 2: Details"]);
  await officeEditor(page).press("Control+Shift+z"); await expect(captions).toHaveText(["Abbildung 1: Details", "Abbildung 2: Overview"]);

  await selectReferenceText(page); await page.locator("#cross-reference-options").click();
  await page.locator("#cross-reference-target").selectOption(ids[1]); await page.locator("#cross-reference-apply").click();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  const marked = saved.content.content[0].content[0];
  expect(marked.marks).toEqual([{ type: "crossReference", attrs: { targetId: ids[1] } }]);
  expect(saved.content.content.filter((entry) => entry.type === "image").map((entry) => entry.attrs.figureId)).toEqual([ids[1], ids[0]]);

  const prints = await installPrintProbe(page, { pdfName: `office-figures-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const target = page.locator(`#print-preview #office-figure-${ids[1]}`);
  await expect(target).toHaveCount(1); await expect(target.locator("figcaption")).toHaveText("Abbildung 1: Details");
  await expect(page.locator("#print-preview a[data-office-cross-reference]")).toHaveAttribute("href", `#office-figure-${ids[1]}`);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-figures-${testInfo.project.name}.png`, fullPage: true });
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints.length).toBe(1); expect(prints[0].pdf.toString("latin1")).toContain("/Subtype /Link");

  await selectImage(page, 0);
  await page.locator("#image-options").click(); await page.locator("#image-remove").click();
  await selectReferenceText(page); await page.locator("#cross-reference-options").click();
  await expect(page.locator('#cross-reference-target option[data-broken="true"]')).toHaveValue(ids[1]);
  await expect(page.locator("#cross-reference-status")).toContainText("Ziel nicht verfügbar");
  await expect(page.locator("#cross-reference-jump")).toBeDisabled(); await page.locator("#cross-reference-cancel").click();
  await officeEditor(page).press("Control+z"); await expect(officeEditor(page).locator(`figure[data-office-figure="${ids[1]}"]`)).toHaveCount(1);
});
