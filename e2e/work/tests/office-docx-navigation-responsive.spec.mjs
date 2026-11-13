import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL } from "./support.mjs";
import {
  OFFICE_READER_HEADERS, officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice,
} from "./office-support.mjs";
import { installPrintProbe, openPrintPreview, submitOfficePrint } from "./office-print-support.mjs";

const sourceId = "work-e2e-stored-docx-navigation";
const sourceVersion = "stored-docx-navigation-v1";
const targetId = "docx-bookmark-7";

test("Office imports stored DOCX bookmarks and jumps only inside the saved document", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  const denied = await page.request.post(`${BASE_URL}/v1/office/documents/import-previews`, {
    headers: { ...OFFICE_READER_HEADERS, "X-Readable-Object-Ids": sourceId },
    data: { source_object_id: sourceId, source_version_id: sourceVersion },
  });
  expect(denied.status()).toBe(403);
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  await page.locator("#document-import").click();
  const dialog = page.locator("#import-document-dialog");
  const source = dialog.locator("#import-source-select");
  await expect(source).toContainText("Synthetische gespeicherte DOCX-Quelle mit Textmarken");
  await source.selectOption(`${sourceId}\u001f${sourceVersion}`);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/office/documents/import-previews");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.source_version_id).toBe(sourceVersion);
  expect(preview.content_persisted).toBe(false);
  await expect(officeEditor(page).locator("[data-office-bookmark]")).toHaveCount(2);
  await expect(officeEditor(page).locator("a[href]")).toHaveCount(0);
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-dialog").getByRole("button", { name: "Weiter bearbeiten" }).click();
  const saved = await saveOffice(page);
  expect(saved.document.information_classification).toBe("confidential");
  const exact = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(exact.content).toEqual(saved.content);
  expect(exact.content.attrs.importProvenance).toEqual(preview.document.attrs.importProvenance);
  expect(exact.content.content[2].content[0].attrs).toEqual({ id: targetId, label: "Section_Target" });
  expect(exact.content.content[0].content[1].marks).toContainEqual({ type: "crossReference", attrs: { targetId } });
  expect(exact.content.content[0].content[1].marks).toContainEqual({ type: "bold" });
  await openOfficeDocument(page, saved.document.object_id);
  const editor = officeEditor(page);
  const link = editor.locator(`[data-office-cross-reference="${targetId}"]`).first();
  const target = editor.locator(`[data-office-bookmark="${targetId}"]`);
  await expect(editor).toHaveAttribute("contenteditable", "true");
  await expect(link).toContainText("Zum Ziel");
  await link.evaluate(async (element) => {
    element.closest('[contenteditable="true"]').focus();
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.locator("#cross-reference-options").click();
  await expect(page.locator("#cross-reference-target")).toHaveValue(targetId);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-docx-navigation-${testInfo.project.name}.png`, fullPage: true });
  const beforeJump = requests.length;
  const beforeUrl = page.url();
  await page.locator("#cross-reference-jump").click();
  await expect(target).toHaveClass(/ProseMirror-selectednode/);
  expect(page.url()).toBe(beforeUrl);
  expect(requests).toHaveLength(beforeJump);

  const prints = await installPrintProbe(page, { pdfName: `office-docx-navigation-${testInfo.project.name}.pdf` });
  await openPrintPreview(page, saved.document.object_id, saved.version.version_id);
  const fragment = `office-bookmark-${targetId}`;
  await expect(page.locator(`#print-preview [id="${fragment}"]`)).toHaveCount(1);
  const links = page.locator("#print-preview a[href]");
  const hrefs = await links.evaluateAll((entries) => entries.map((entry) => entry.getAttribute("href")));
  expect(hrefs.length).toBeGreaterThan(0);
  expect(new Set(hrefs)).toEqual(new Set([`#${fragment}`]));
  await submitOfficePrint(page, saved.document.object_id, saved.version.version_id);
  await expect.poll(() => prints[0]?.pdf || null).not.toBeNull();
  const pdf = prints[0].pdf.toString("latin1");
  expect(pdf).toContain("/Subtype /Link");
  expect(pdf).toContain(`/Dest /${fragment}`);
  expect(pdf).toMatch(/\/Dests\b/);
  expect(pdf).not.toContain("/URI");
  await expect(page.locator(`#print-preview [id="${fragment}"]`)).toHaveCount(1);
  expect(requests.some((url) => url.includes("office-navigation.invalid"))).toBe(false);
});
