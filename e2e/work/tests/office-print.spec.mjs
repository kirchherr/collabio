import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, createOfficeDocument, holdOfficeRead, newOfficeDraft,
  officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument, saveOffice, setOfficeAcl,
} from "./office-support.mjs";
import {
  PRINT_WHITESPACE, collectOfficePrintRequests, createPrintFixture, expectPdfStructure, expectPrintCleared, installPrintProbe,
  observeLatePrint, openPrintHistory, openPrintPreview, pdfPageCount, refreshPrintPreview, submitOfficePrint,
} from "./office-print-support.mjs";

test("Office prints the freshly authorized exact rich version to a real multipage PDF without shell or active markup", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const saved = await createPrintFixture(page);
  const objectId = saved.document.object_id;
  const versionId = saved.version.version_id;
  await openOffice(page);
  await openOfficeDocument(page, objectId);
  const requests = collectOfficePrintRequests(page);
  const calls = await installPrintProbe(page, { pdfName: "office-print-rich-letter-landscape.pdf" });
  await openPrintPreview(page, objectId, versionId, { keyboard: "Control+p" });
  await expect(page.locator("#print-preview")).toContainText(saved.version.title);
  await expect(page.locator("#print-preview")).toContainText("LAST_PRINT_PROOF_SENTINEL");
  await expect(page.locator("#print-preview img, #print-preview script")).toHaveCount(0);
  await page.locator("#print-close").click();
  await expectPrintCleared(page);
  await openPrintPreview(page, objectId, versionId, { keyboard: "Meta+p" });
  await page.locator("#print-paper").selectOption("letter");
  await page.locator("#print-orientation").selectOption("landscape");
  await submitOfficePrint(page, objectId, versionId);
  await expect.poll(() => calls[0]?.pdf?.length || 0).toBeGreaterThan(1000);
  expect(calls).toHaveLength(1);
  const { snapshot, layout, pdf } = calls[0];
  expect(snapshot.ready).toBe(true);
  expect(snapshot.className).toContain("paper-letter");
  expect(snapshot.className).toContain("orientation-landscape");
  expect(snapshot.headings).toContain("Printable section");
  expect(snapshot.marks).toEqual(expect.arrayContaining([
    { tag: "STRONG", text: "Bold" }, { tag: "EM", text: " Italic" },
    { tag: "U", text: " Underline" }, { tag: "S", text: " Strike" }, { tag: "CODE", text: " Code" },
  ]));
  expect(snapshot.orderedStarts).toContain(7);
  expect(snapshot.whitespace).toEqual([{ text: PRINT_WHITESPACE, whiteSpace: "pre-wrap" }]);
  expect(snapshot.tables).toEqual([{ rows: 3, columns: 20, headers: 20 }]);
  expect(snapshot.unsafeElements).toBe(0);
  expect(snapshot.text).toContain('onerror="window.printExecuted=true"');
  expect(snapshot.text).toContain("LAST_PRINT_PROOF_SENTINEL");
  expect(snapshot.text).not.toContain("work-office-editor-e2e");
  expect(layout).toMatchObject({ rootVisible: true, shellVisible: false, dialogVisible: false, guidanceVisible: false });
  expect(layout.overflow).not.toContain(true);
  const pageCount = pdfPageCount(pdf, 792, 612);
  expectPdfStructure(pdf, ["H1", "P", "Table", "TH", "TD", "L", "LI"]);
  expect(pageCount).toBeGreaterThan(1);
  expect(pageCount).toBeLessThan(30);
  await expectPrintCleared(page);
  expect(await page.evaluate(() => window.printExecuted)).toBeUndefined();
  expect(requests.every((request) => request.method === "GET")).toBe(true);
  expect(requests.filter((request) => new URL(request.url).pathname.endsWith("/content")).every((request) => new URL(request.url).searchParams.get("version_id") === versionId)).toBe(true);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  verifyBrowser();
});

test("Office ordinary readers print an exact historical version with its historical title while writes stay disabled", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Historical print title", "Historical printable wording");
  const objectId = first.document.object_id;
  await page.locator("#document-title").fill("Current title must not replace history");
  await officeEditor(page).fill("Current protected text must not print with history");
  const second = await saveOffice(page, { objectId });
  await setOfficeAcl(page, objectId);
  await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(page, objectId);
  await openPrintHistory(page, objectId, first.version.version_id);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  const calls = await installPrintProbe(page, { pdfName: "office-print-history-a4-portrait.pdf" });
  const requests = collectOfficePrintRequests(page);
  const preview = await openPrintPreview(page, objectId, first.version.version_id);
  expect(preview.can_write).toBe(false);
  expect(preview.is_current_version).toBe(false);
  await expect(page.locator("#print-preview")).toContainText("Historical print title");
  await expect(page.locator("#print-preview")).not.toContainText(second.version.title);
  await submitOfficePrint(page, objectId, first.version.version_id);
  await expect.poll(() => calls[0]?.pdf?.length || 0).toBeGreaterThan(1000);
  expect(calls).toHaveLength(1);
  expect(pdfPageCount(calls[0].pdf, 594.96, 841.92)).toBe(1);
  expectPdfStructure(calls[0].pdf, ["H1", "P"]);
  expect(calls[0].snapshot.text).toContain("Historical printable wording");
  expect(calls[0].snapshot.text).not.toContain("Current protected text");
  expect(calls[0].snapshot.text).not.toContain(second.version.title);
  expect(requests).toHaveLength(2);
  expect(requests.every((request) => request.method === "GET" && new URL(request.url).searchParams.get("version_id") === first.version.version_id)).toBe(true);
  await expectPrintCleared(page);
  expect(await officeVersions(page, objectId)).toHaveLength(2);
});

test("Office blocks new dirty busy and uncertain printing and raw print media exposes only safe guidance", async ({ page }) => {
  await openOffice(page);
  const calls = await installPrintProbe(page);
  await newOfficeDraft(page, "Never print an unsaved draft", { text: "PRIVATE_UNSAVED_PRINT_SOURCE" });
  await expect(page.locator("#document-print")).toBeDisabled();
  await page.keyboard.press("Control+p");
  await expect(page.locator("#print-dialog")).toBeHidden();
  const first = await saveOffice(page);
  const objectId = first.document.object_id;
  await officeEditor(page).fill("PRIVATE_DIRTY_PRINT_SOURCE");
  await expect(page.locator("#document-print")).toBeDisabled();
  await page.keyboard.press("Meta+p");
  await expect(page.locator("#print-dialog")).toBeHidden();
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("#office-shell")).toBeHidden();
  await expect(page.locator("#office-editor")).toBeHidden();
  await expect(page.locator("#context-form")).toBeHidden();
  await expect(page.locator("#print-dialog")).toBeHidden();
  await expect(page.locator("#office-print-guidance")).toBeVisible();
  await expect(page.locator("#office-print-guidance")).not.toContainText("PRIVATE_");
  await page.pdf({ path: `${ARTIFACT_DIR}/office-print-unprepared.pdf`, preferCSSPageSize: true, printBackground: true });
  await page.emulateMedia({ media: "screen" });
  await expectPrintCleared(page);
  let release;
  let started;
  let delivered;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  const delivery = new Promise((resolve) => { delivered = resolve; });
  await page.route((url) => url.pathname === `${OFFICE_PATH}/${objectId}/versions`, async (route) => {
    started();
    await gate;
    const response = await route.fetch({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" }, maxRetries: 0, maxRedirects: 0 });
    expect(response.status()).toBe(503);
    const body = await response.body();
    expect(JSON.parse(body.toString("utf8")).detail).toBe("Office storage unavailable");
    await route.fulfill({ response, body });
    delivered();
  }, { times: 1 });
  try {
    await page.locator("#document-save").click();
    await page.locator("#save-confirm").check();
    await page.locator("#save-submit").click();
    await ready;
    await expect(page.locator("#document-print")).toBeDisabled();
    await page.keyboard.press("Control+p");
    await expect(page.locator("#print-dialog")).toBeHidden();
    release();
    await delivery;
    await expect(page.locator("#save-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toContainText("Speicherung prüfen");
    await expect(page.locator("#document-print")).toBeDisabled();
    await page.keyboard.press("Control+p");
    await expect(page.locator("#print-dialog")).toBeHidden();
    expect(calls).toHaveLength(0);
    expect((await officeContent(page, objectId)).version.version_id).toBe(first.version.version_id);
  } finally { release(); }
});

test("Office denies preview after parent revocation and rechecks rights again before calling native print", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic revoked print", "Protected print source");
  const objectId = first.document.object_id;
  const versionId = first.version.version_id;
  await setOfficeAcl(page, objectId);
  await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(page, objectId);
  const calls = await installPrintProbe(page);
  await setOfficeAcl(page, objectId, { status: "revoked" });
  await openPrintPreview(page, objectId, versionId, { status: 404 });
  await expect(page.locator("#document-workspace")).toBeHidden();
  expect(calls).toHaveLength(0);
  await expectPrintCleared(page);
  await setOfficeAcl(page, objectId);
  await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(page, objectId);
  // The exposed Node bridge survives navigation; the page-local native stub does not.
  await page.evaluate(() => { window.print = () => window.officeE2EPrint({ unexpected: true }); });
  await openPrintPreview(page, objectId, versionId);
  await setOfficeAcl(page, objectId, { status: "revoked" });
  await submitOfficePrint(page, objectId, versionId, { status: 404 });
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#print-preview")).toHaveText("");
  expect(calls).toHaveLength(0);
  await expectPrintCleared(page);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});

test("Office clears unavailable print content and retries exact source reads without printing stale bytes", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic print storage failure", "Fresh print retry source");
  const objectId = first.document.object_id;
  const versionId = first.version.version_id;
  const calls = await installPrintProbe(page);
  await openPrintPreview(page, objectId, versionId, { status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  expect(calls).toHaveLength(0);
  await refreshPrintPreview(page, objectId, versionId);
  await expect(page.locator("#print-preview")).toContainText("Fresh print retry source");
  await submitOfficePrint(page, objectId, versionId, { status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  await expect(page.locator("#print-preview")).toHaveText("");
  await expect(page.locator("#print-submit")).toBeDisabled();
  await expectPrintCleared(page);
  expect(calls).toHaveLength(0);
  await refreshPrintPreview(page, objectId, versionId);
  await submitOfficePrint(page, objectId, versionId);
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].snapshot.text).toContain("Fresh print retry source");
  await expectPrintCleared(page);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});

test("Office close and context changes discard late exact-version print responses", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic late print", "Late protected print wording");
  const objectId = first.document.object_id;
  const versionId = first.version.version_id;
  const calls = await installPrintProbe(page);
  await observeLatePrint(page, "Late protected print wording");
  const closed = await holdOfficeRead(page, objectId, { versionId });
  try {
    await page.locator("#document-print").click();
    await closed.ready;
    await page.locator("#print-close").click();
    await closed.complete();
    await expect(page.locator("#print-dialog")).toBeHidden();
    await expect(page.locator("#print-preview")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficePrint)).toBe(false);
  } finally { closed.release(); }
  await openPrintPreview(page, objectId, versionId);
  await page.evaluate(() => { window.staleOfficePrint = false; });
  const changed = await holdOfficeRead(page, objectId, { versionId });
  try {
    await page.locator("#print-submit").click();
    await changed.ready;
    const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    await page.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect((await pending).status()).toBe(200);
    await changed.complete();
    await expect(page.locator("#print-dialog")).toBeHidden();
    await expect(page.locator("#print-preview")).toHaveText("");
    await expect(page.locator("#office-editor")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficePrint)).toBe(false);
    expect(calls).toHaveLength(0);
    await expectPrintCleared(page);
  } finally { changed.release(); }
});
