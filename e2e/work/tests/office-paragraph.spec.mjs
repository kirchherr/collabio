import { expect, test as base } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, loadOfficeComparison, officeContent, officeContentPath,
  officeEditor, officeFeatures, officeVersions, openOffice, openOfficeComparison, openOfficeDocument,
  saveOffice, setOfficeAcl, setOfficeFeatures,
} from "./office-support.mjs";
import {
  expectPdfStructure, expectPrintCleared, installPrintProbe, openPrintHistory, openPrintPreview,
  pdfPageCount, submitOfficePrint,
} from "./office-print-support.mjs";
import { expectReuseDraft, openReuse, submitReuse } from "./office-reuse-support.mjs";
import {
  FORMAT_IDS, PARAGRAPH_ALTERNATE, PARAGRAPH_FORMAT, applyParagraphFormat, chooseParagraphFormat,
  createParagraphFixture, expectParagraphStyle, formatBlocks, openParagraphDialog, paragraph,
  paragraphBlocks, paragraphWrites, selectParagraphBlocks, withoutParagraphFormat,
} from "./paragraph-helper.mjs";

const test = base.extend({
  paragraphFeatureRestore: [async ({ page }, use) => {
    const state = { features: null };
    await use(state);
    if (state.features) await setOfficeFeatures(page, state.features);
  }, { timeout: 20_000 }],
});

test("Office persists paragraph formatting across headings lists quotations and selected table cells without changing text or marks", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createParagraphFixture(page, "Synthetic paragraph persistence");
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  const writes = paragraphWrites(page, first.document.object_id);
  await selectParagraphBlocks(page, 0, 5);
  await applyParagraphFormat(page, PARAGRAPH_FORMAT, { count: 6 });
  for (const block of await paragraphBlocks(page).all()) await expectParagraphStyle(block, PARAGRAPH_FORMAT);
  await officeEditor(page).locator("td").first().click();
  await page.locator("#table-select").selectOption("cell");
  await expect(officeEditor(page).locator(".selectedCell")).toHaveCount(1);
  await applyParagraphFormat(page, PARAGRAPH_ALTERNATE, { count: 1 });
  await expectParagraphStyle(paragraphBlocks(page).nth(4), PARAGRAPH_ALTERNATE);
  await expectParagraphStyle(paragraphBlocks(page).nth(5), PARAGRAPH_FORMAT);
  await selectParagraphBlocks(page, 0);
  await page.locator("#text-style").selectOption("paragraph");
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await page.locator("#text-style").selectOption("heading-2");
  await expectParagraphStyle(officeEditor(page).locator("h2"), PARAGRAPH_FORMAT);
  expect(writes).toHaveLength(0);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  const expected = formatBlocks(first.content, PARAGRAPH_FORMAT);
  expected.content[4].content[0].content[0].content[0].attrs = PARAGRAPH_ALTERNATE;
  expect(second.content).toEqual(expected);
  expect(withoutParagraphFormat(second.content)).toEqual(first.content);
  expect(writes).toHaveLength(1);
  expect(writes[0].human_confirmation).toBe(true);
  expect(second.version.previous_version_id).toBe(first.version.version_id);
  await page.locator("#document-close").click();
  const reopened = await openOfficeDocument(page, first.document.object_id);
  expect(reopened.content).toEqual(expected);
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await expectParagraphStyle(paragraphBlocks(page).nth(4), PARAGRAPH_ALTERNATE);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
  verifyBrowser();
});

test("Office mixed paragraph formatting changes only chosen fields and undoes independently from adjacent typing", async ({ page }) => {
  const content = { type: "doc", content: [paragraph("First", PARAGRAPH_FORMAT, ["bold"]), paragraph("Second", PARAGRAPH_ALTERNATE)] };
  const first = await createParagraphFixture(page, "Synthetic paragraph undo", content);
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0, 0, { caret: true });
  await page.keyboard.type(" BEFORE");
  await selectParagraphBlocks(page, 0, 1);
  await openParagraphDialog(page, 2);
  for (const id of Object.values(FORMAT_IDS)) await expect(page.locator(`#${id}`)).toHaveValue("mixed");
  await chooseParagraphFormat(page, { lineSpacing: "1.15" });
  await page.locator("#paragraph-apply").click();
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
  await expectParagraphStyle(paragraphBlocks(page).first(), { ...PARAGRAPH_FORMAT, lineSpacing: "1.15" });
  await expectParagraphStyle(paragraphBlocks(page).last(), { ...PARAGRAPH_ALTERNATE, lineSpacing: "1.15" });
  await selectParagraphBlocks(page, 0, 0, { caret: true });
  await page.keyboard.type(" AFTER");
  await officeEditor(page).press("Control+z");
  await expect(paragraphBlocks(page).first()).toHaveText("First BEFORE");
  await expectParagraphStyle(paragraphBlocks(page).first(), { lineSpacing: "1.15" });
  await officeEditor(page).press("Control+z");
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await expectParagraphStyle(paragraphBlocks(page).last(), PARAGRAPH_ALTERNATE);
  await expect(paragraphBlocks(page).first()).toHaveText("First BEFORE");
  await officeEditor(page).press("Control+z");
  await expect(paragraphBlocks(page).first()).toHaveText("First");
  await expect(page.locator("#document-save")).toBeDisabled();
  for (let step = 0; step < 3; step += 1) await officeEditor(page).press("Control+Shift+z");
  await expect(paragraphBlocks(page).first()).toHaveText("First BEFORE AFTER");
  await expectParagraphStyle(paragraphBlocks(page).first(), { ...PARAGRAPH_FORMAT, lineSpacing: "1.15" });
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office paragraph cancel reset and no-op preserve clean state and unsupported code stays unavailable", async ({ page }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph defaults", { type: "doc", content: [
    paragraph("Legacy paragraph"), { type: "codeBlock", content: [{ type: "text", text: "Code only" }] },
  ] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  const writes = paragraphWrites(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await openParagraphDialog(page, 1);
  for (const id of Object.values(FORMAT_IDS)) await expect(page.locator(`#${id}`)).toHaveValue("default");
  await page.locator("#paragraph-apply").click();
  await expect(page.locator("#paragraph-status")).toContainText("Keine Änderung");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await chooseParagraphFormat(page, PARAGRAPH_FORMAT);
  await page.locator("#paragraph-cancel").click();
  await expect(officeEditor(page)).toBeFocused();
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await applyParagraphFormat(page, PARAGRAPH_FORMAT);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await openParagraphDialog(page);
  await page.locator("#paragraph-reset").click();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await page.locator("#paragraph-cancel").click();
  await expect(page.locator("#document-save")).toBeDisabled();
  await openParagraphDialog(page);
  await page.locator("#paragraph-reset").click();
  await page.locator("#paragraph-apply").click();
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  const reset = await saveOffice(page, { objectId: first.document.object_id });
  expect(reset.content).toEqual(first.content);
  expect(reset.version.previous_version_id).toBe(second.version.version_id);
  await officeEditor(page).locator("pre").evaluate((element) => {
    const range = document.createRange(); range.selectNodeContents(element); range.collapse(false);
    element.closest(".tiptap").focus(); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator("#paragraph-format")).toBeDisabled();
  expect(writes).toHaveLength(2);
});

test("Office heading shortcuts split input rules list wrapping replacement and reuse retain paragraph attributes", async ({ page }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph transforms", { type: "doc", content: [paragraph("Alpha replace target", PARAGRAPH_FORMAT)] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await page.locator("#text-style").selectOption("heading-2");
  await expectParagraphStyle(officeEditor(page).locator("h2"), PARAGRAPH_FORMAT);
  await officeEditor(page).press("Control+Alt+3");
  await expectParagraphStyle(officeEditor(page).locator("h3"), PARAGRAPH_FORMAT);
  await officeEditor(page).press("Control+Alt+0");
  await expect(officeEditor(page).locator("h1,h2,h3")).toHaveCount(0);
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await selectParagraphBlocks(page, 0, 0, { caret: true });
  await page.keyboard.press("Enter");
  await page.keyboard.type("Split child");
  await expect(paragraphBlocks(page)).toHaveCount(2);
  await expectParagraphStyle(paragraphBlocks(page).last(), PARAGRAPH_FORMAT);
  await page.keyboard.press("Enter");
  await page.keyboard.type("# ");
  await page.keyboard.type("Input rule heading");
  await expectParagraphStyle(officeEditor(page).locator("h1"), PARAGRAPH_FORMAT);
  await officeEditor(page).press("Control+Shift+8");
  await expect(officeEditor(page).locator("ul li p")).toHaveText("Input rule heading");
  await expectParagraphStyle(officeEditor(page).locator("ul li p"), PARAGRAPH_FORMAT);
  await page.locator("#find-toggle").click();
  await page.locator("#find-query").fill("replace");
  await page.locator("#replace-query").fill("changed");
  await page.locator("#replace-all").click();
  await expect(page.locator("#find-message")).toContainText("1 Treffer ersetzt");
  await page.locator("#find-close").click();
  await expect(paragraphBlocks(page).first()).toHaveText("Alpha changed target");
  for (const block of await paragraphBlocks(page).all()) await expectParagraphStyle(block, PARAGRAPH_FORMAT);
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content).toEqual(formatBlocks(withoutParagraphFormat(saved.content), PARAGRAPH_FORMAT));
  const writes = paragraphWrites(page, first.document.object_id);
  await openReuse(page, saved, "Independent formatted copy");
  await submitReuse(page, saved);
  await expectReuseDraft(page, "Independent formatted copy");
  for (const block of await paragraphBlocks(page).all()) await expectParagraphStyle(block, PARAGRAPH_FORMAT);
  expect(writes).toHaveLength(0);
  const copied = await saveOffice(page);
  expect(copied.content).toEqual(saved.content);
  expect(copied.document.object_id).not.toBe(first.document.object_id);
  expect(await officeVersions(page, copied.document.object_id)).toHaveLength(1);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office compares format-only versions and restores exact paragraph attributes through an explicit new save", async ({ page }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph versions", { type: "doc", content: [paragraph("Same saved wording", PARAGRAPH_FORMAT)] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, PARAGRAPH_ALTERNATE);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(withoutParagraphFormat(first.content)).toEqual(withoutParagraphFormat(second.content));
  const writes = paragraphWrites(page, first.document.object_id);
  await openOfficeComparison(page);
  await loadOfficeComparison(page, first.document.object_id, first.version.version_id, second.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("1 geändert");
  await expect(page.locator('#compare-results [data-change-kind="changed"]')).toHaveCount(1);
  await expect(page.locator("#compare-results")).toContainText("Same saved wording");
  for (const label of ["Ausrichtung: Zentriert", "Ausrichtung: Rechtsbündig", "Zeilenabstand: 1,5", "Zeilenabstand: 2", "Abstand davor: 6 pt", "Abstand danach: 24 pt"]) {
    await expect(page.locator("#compare-results")).toContainText(label);
  }
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  const third = await saveOffice(page, { objectId: first.document.object_id });
  expect(third.content).toEqual(first.content);
  expect(third.version.previous_version_id).toBe(second.version.version_id);
  await openOfficeComparison(page);
  await loadOfficeComparison(page, first.document.object_id, first.version.version_id, third.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("0 geändert");
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(3);
});

test("Office readers and history cannot format while fresh write loss preserves an unsaved formatted draft", async ({ page, context, paragraphFeatureRestore }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph permissions", { type: "doc", content: [paragraph("Protected paragraph", PARAGRAPH_FORMAT)] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, PARAGRAPH_ALTERNATE);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  await openPrintHistory(page, first.document.object_id, first.version.version_id);
  await expect(page.locator("#paragraph-format")).toBeDisabled();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await page.locator("#document-reload").click();
  await expect(page.locator("#document-version")).toContainText(second.version.version_id);
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  try {
    await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
    await openOfficeDocument(reader, first.document.object_id);
    await expect(reader.locator("#paragraph-format")).toBeDisabled();
    await expectParagraphStyle(paragraphBlocks(reader).first(), PARAGRAPH_ALTERNATE);
  } finally { await reader.close(); }
  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, PARAGRAPH_FORMAT);
  paragraphFeatureRestore.features = await officeFeatures(page);
  await setOfficeFeatures(page, { ...paragraphFeatureRestore.features, "office_documents.documents.write": false });
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(first.document.object_id));
  await page.locator("#documents-refresh").click();
  const refreshed = await pending;
  expect(refreshed.status()).toBe(200);
  expect((await refreshed.json()).can_write).toBe(false);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  await expect(page.locator("#paragraph-format")).toBeDisabled();
  await expect(page.locator("#document-save")).toBeDisabled();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  expect((await officeContent(page, first.document.object_id)).content).toEqual(second.content);
});

test("Office freezes paragraph actions while saving and retries an uncertain save with identical formatting and mutation identity", async ({ page }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph uncertain", { type: "doc", content: [paragraph("Uncertain formatting")] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, PARAGRAPH_FORMAT);
  const writes = paragraphWrites(page, first.document.object_id);
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let release; let started; let captured;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  const upstream = new Promise((resolve) => { captured = resolve; });
  await page.route((url) => url.pathname === path, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    started(); await gate;
    const response = await route.fetch({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" }, maxRetries: 0, maxRedirects: 0 });
    const body = await response.body();
    const result = { status: response.status(), headers: response.headers(), json: JSON.parse(body.toString("utf8")) };
    await route.fulfill({ response, body }); captured(result);
  }, { times: 1 });
  try {
    await page.locator("#document-save").click();
    await page.locator("#save-confirm").check();
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click(); await ready;
    await expect(page.locator("#paragraph-format")).toBeDisabled();
    await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
    release();
    const response = await failed;
    expect(response.status()).toBe(503);
    expect(response.headers()["cache-control"]).toContain("no-store");
    const actual = await upstream;
    expect(actual.status).toBe(503);
    expect(actual.json.detail).toBe("Office storage unavailable");
    await expect(page.locator("#save-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expect(page.locator("#paragraph-format")).toBeDisabled();
    await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
    const retried = await saveOffice(page, { objectId: first.document.object_id });
    expect(writes).toHaveLength(2);
    expect(writes[1]).toEqual(writes[0]);
    expect(retried.content).toEqual(formatBlocks(first.content, PARAGRAPH_FORMAT));
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  } finally { release(); }
});

test("Office paragraph dialog cancellation and context changes cannot apply stale choices or discard a draft silently", async ({ page }) => {
  const first = await createParagraphFixture(page, "Synthetic paragraph context", { type: "doc", content: [paragraph("Keep this draft")] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0);
  await applyParagraphFormat(page, PARAGRAPH_FORMAT);
  await page.locator("#document-close").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  await expect(page.locator("#document-save")).toBeEnabled();
  await selectParagraphBlocks(page, 0);
  await openParagraphDialog(page);
  await chooseParagraphFormat(page, PARAGRAPH_ALTERNATE);
  await page.keyboard.press("Escape");
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
  await expectParagraphStyle(paragraphBlocks(page).first(), PARAGRAPH_FORMAT);
  const writes = paragraphWrites(page, first.document.object_id);
  await openParagraphDialog(page);
  await chooseParagraphFormat(page, PARAGRAPH_ALTERNATE);
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#readable-object-ids").value = "";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await expect(page.locator("#discard-dialog")).toBeVisible();
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.locator("#discard-confirm").click(); expect((await changed).status()).toBe(200);
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#office-editor")).toHaveText("");
  expect(writes).toHaveLength(0);
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
});

test("Office prints exact saved paragraph alignment and spacing into a tagged multipage PDF", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createParagraphFixture(page, "Paragraph PDF <b>literal title</b>", { type: "doc", content: [
    { type: "heading", attrs: { level: 2, ...PARAGRAPH_FORMAT }, content: [{ type: "text", text: "PARAGRAPH_FORMAT_PDF_HEAD" }] },
    ...Array.from({ length: 28 }, (_, index) => paragraph(`PARAGRAPH_${String(index).padStart(2, "0")} Café 😀. ${"Exact saved spacing and alignment. ".repeat(4)}`, index % 2 ? PARAGRAPH_FORMAT : PARAGRAPH_ALTERNATE)),
    paragraph("PARAGRAPH_FORMAT_PDF_LAST", PARAGRAPH_ALTERNATE),
  ] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  const calls = await installPrintProbe(page, { pdfName: "office-paragraph-a4-portrait.pdf" });
  await page.exposeFunction("measureParagraphPrint", async () => {
    await page.emulateMedia({ media: "print" });
    return page.evaluate(() => [...document.querySelectorAll("#office-print-root p,#office-print-root h2")].map((element) => {
      const style = getComputedStyle(element);
      return { text: element.textContent, align: style.textAlign, line: parseFloat(style.lineHeight) / parseFloat(style.fontSize), before: parseFloat(style.marginTop), after: parseFloat(style.marginBottom) };
    }));
  });
  await page.evaluate(() => {
    const print = window.print;
    window.print = async () => {
      window.paragraphPrintStyles = await window.measureParagraphPrint();
      return print();
    };
  });
  await openPrintPreview(page, first.document.object_id, first.version.version_id);
  await expectParagraphStyle(page.locator("#print-preview h2"), PARAGRAPH_FORMAT);
  await expectParagraphStyle(page.locator("#print-preview p").first(), PARAGRAPH_ALTERNATE);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-paragraph-print-preview.png`, fullPage: true });
  await submitOfficePrint(page, first.document.object_id, first.version.version_id);
  await expect.poll(() => calls[0]?.pdf?.length || 0).toBeGreaterThan(1000);
  expect(calls).toHaveLength(1);
  expectPdfStructure(calls[0].pdf, ["H1", "H2", "P"]);
  const pages = pdfPageCount(calls[0].pdf, 594.96, 841.92);
  expect(pages).toBeGreaterThan(1); expect(pages).toBeLessThan(20);
  expect(calls[0].snapshot.text).toContain("PARAGRAPH_FORMAT_PDF_LAST");
  expect(calls[0].snapshot.unsafeElements).toBe(0);
  expect(calls[0].layout).toMatchObject({ rootVisible: true, shellVisible: false, dialogVisible: false });
  const styles = await page.evaluate(() => window.paragraphPrintStyles);
  expect(styles[0]).toMatchObject({ align: "center", before: 8, after: 16 });
  expect(styles[0].line).toBeCloseTo(1.5, 2);
  expect(styles[1]).toMatchObject({ align: "right", before: 24, after: 32 });
  expect(styles[1].line).toBeCloseTo(2, 2);
  await expectPrintCleared(page);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  verifyBrowser();
});
