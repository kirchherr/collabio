import { test, expect } from "@playwright/test";
import { BASE_URL, BLOCKED_BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { OFFICE_PATH, OFFICE_HEADERS, OFFICE_READER_ID, officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument,
  saveOffice, setOfficeAcl, openOfficeComparison, loadOfficeComparison } from "./office-support.mjs";
import { styleFixture, styleDocument } from "./style-helper.mjs";
import { installPrintProbe, pdfPageCount, expectPdfStructure } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const profile = (paper = "letter", orientation = "landscape") => ({ paper, orientation, margins: { top: 12, right: 25, bottom: 30, left: 40 } });
async function openSettings(page) { await page.locator("#page-options").click(); await expect(page.locator("#page-dialog")).toBeVisible(); }
async function choose(page, value = profile()) {
  await page.locator("#page-paper").selectOption(value.paper); await page.locator("#page-orientation").selectOption(value.orientation);
  for (const [side, margin] of Object.entries(value.margins)) await page.locator(`#page-${side}`).fill(String(margin));
}
async function apply(page, value = profile()) {
  await openSettings(page); await choose(page, value); await page.locator("#page-apply").click();
  await expect(page.locator("#page-dialog")).toBeHidden(); await expect(officeEditor(page)).toBeFocused();
}

test("Office page settings preview cancel no-op invalid values and isolated typing undo", async ({ page }, testInfo) => {
  const first = await styleFixture(page, { type: "doc", content: [p("Page settings text")] });
  await openSettings(page); await page.locator("#page-apply").click(); await expect(page.locator("#page-status")).toContainText("Keine Änderung");
  await choose(page); await page.locator("#page-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).click(); await page.keyboard.press("Control+End"); await page.keyboard.press("Control+b");
  await openSettings(page); await choose(page);
  await page.locator("#page-left").fill("51"); await expect(page.locator("#page-apply")).toBeDisabled();
  await page.locator("#page-left").fill("40.5"); await expect(page.locator("#page-apply")).toBeDisabled();
  await page.locator("#page-left").fill("40"); await expect(page.locator("#page-apply")).toBeEnabled();
  await expect(page.locator("#page-description")).toContainText("links 40 mm");
  expect(await page.locator("#page-dialog").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-page-settings-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#page-apply").click(); await page.keyboard.type("X");
  await expect(officeEditor(page).locator("strong")).toHaveText("X"); await page.keyboard.press("Control+z");
  await expect(officeEditor(page)).toHaveText("Page settings text"); await expect(page.locator("#document-page")).toHaveClass(/has-page-settings/);
  await page.keyboard.press("Control+z"); await expect(page.locator("#document-page")).not.toHaveClass(/has-page-settings/);
  await expect(page.locator("#document-save")).toBeDisabled(); await page.keyboard.press("Control+Shift+z");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.attrs.page).toEqual(profile()); expect(saved.content.content).toEqual(first.content.content);
});

test("Office page settings preserve styles breaks immutable history comparison reset and owned copies", async ({ page }) => {
  const content = styleDocument(); content.content.splice(2, 0, { type: "pageBreak" });
  const first = await styleFixture(page, content), objectId = first.document.object_id;
  await apply(page); const custom = await saveOffice(page, { objectId });
  expect(custom.content.attrs.styles).toEqual(content.attrs.styles); expect(custom.content.content).toEqual(content.content);
  await openSettings(page); await page.locator("#page-reset").click(); await page.locator("#page-apply").click();
  const reset = await saveOffice(page, { objectId }); expect(reset.content).toEqual(first.content);
  expect((await officeContent(page, objectId, { versionId: custom.version.version_id })).content).toEqual(custom.content);
  await openOfficeComparison(page); await loadOfficeComparison(page, objectId, custom.version.version_id, reset.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("Seiteneinstellungen"); await expect(page.locator("#compare-results")).toContainText("links 40 mm");
  await page.locator("#compare-close").click(); await openReuseHistory(page, custom);
  await expect(page.locator("#page-options")).toBeDisabled(); await expect(page.locator("#document-page")).toHaveClass(/has-page-settings/);
  await openReuse(page, custom, "Independent page settings"); await submitReuse(page, custom); await expectReuseDraft(page, "Independent page settings");
  const copied = await saveOffice(page); expect(copied.content).toEqual(custom.content); expect(copied.document.object_id).not.toBe(objectId);
});

test("Office page settings respect read-only pending uncertain and changed-context boundaries", async ({ page, context }) => {
  const first = await styleFixture(page); await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage(); await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id); await expect(reader.locator("#page-options")).toBeDisabled();
  await apply(page);
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let release, started; const gate = new Promise((resolve) => { release = resolve; }); const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${path}`, async (route) => { started(); await gate;
    const response = await route.fetch({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" }, maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({ response }); }, { times: 1 });
  try {
    await page.locator("#document-save").click(); await page.locator("#save-confirm").check();
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click(); await ready; await expect(page.locator("#page-options")).toBeDisabled(); release();
    expect((await failed).status()).toBe(503); await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expect(page.locator("#page-options")).toBeDisabled(); expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
    const saved = await saveOffice(page, { objectId: first.document.object_id }); expect(saved.content.attrs.page).toEqual(profile());
  } finally { release(); }
  await openSettings(page); await page.evaluate(() => { document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await expect(page.locator("#page-dialog")).toBeHidden(); await expect(page.locator("#page-description")).toBeEmpty();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office page settings reject canonical byte overflow without changing a valid draft", async ({ page }) => {
  const content = { type: "doc", content: [p("界".repeat(66000))] };
  const bytes = (value) => JSON.stringify(value).replace(/[^\x00-\x7f]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`).length;
  content.content[0].content[0].text += "a".repeat(399990 - bytes(content));
  await styleFixture(page, content); await openSettings(page); await choose(page); await page.locator("#page-apply").click();
  await expect(page.locator("#page-status")).toContainText("Dokumentgrenzen"); await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator("#document-page")).not.toHaveClass(/has-page-settings/);
});

for (const paper of ["a4", "letter"]) for (const orientation of ["portrait", "landscape"]) {
  test(`Office saved page settings produce exact ${paper} ${orientation} PDF with margins images breaks and tables`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const geometry = profile(paper, orientation);
    const initial = await styleFixture(page, { type: "doc", content: [p("PAGE-SETTINGS-FIRST")] });
    const bytes = Buffer.from(await page.evaluate(() => { const canvas = document.createElement("canvas"); canvas.width = 80; canvas.height = 80;
      canvas.getContext("2d").fillStyle = "#2563eb"; canvas.getContext("2d").fillRect(0, 0, 80, 80); return canvas.toDataURL().split(",")[1]; }), "base64");
    const upload = await page.request.post(`${BASE_URL}${OFFICE_PATH}/${initial.document.object_id}/images`, {
      headers: { ...OFFICE_HEADERS, "Content-Type": "image/png", "X-Office-Upload-Confirmed": "true" }, data: bytes });
    expect(upload.status()).toBe(200);
    const image = { type: "image", attrs: { ...(await upload.json()).image, width: 120, height: 120, alt: "Page geometry blue image", decorative: false,
      caption: "PAGE-SETTINGS-IMAGE", wrap: { side: "left", gap: 16 }, align: "left" } };
    const row = (type, a, b) => ({ type: "tableRow", content: [a, b].map((text) => ({ type, attrs: { colspan: 1, rowspan: 1 }, content: [p(text)] })) });
    const document = { type: "doc", attrs: { page: geometry }, content: [p("PAGE-SETTINGS-FIRST"), image, p("Text beside the image."), { type: "pageBreak" },
      { type: "table", content: [row("tableHeader", "PAGE-SETTINGS-HEADER", "Second column"), row("tableCell", "PAGE-SETTINGS-LAST", "Final cell")] }] };
    const posted = await page.request.post(`${BASE_URL}${OFFICE_PATH}/${initial.document.object_id}/versions`, { headers: OFFICE_HEADERS, data: {
      title: "Page geometry proof", document, human_confirmation: true, expected_current_version_id: initial.version.version_id, mutation_reference: `page-pdf-${initial.version.version_id}` } });
    expect(posted.status()).toBe(200); const saved = await posted.json();
    await page.locator("#document-reload").click(); await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
    const prints = await installPrintProbe(page, { pdfName: `office-page-settings-${paper}-${orientation}-${testInfo.project.name}.pdf` });
    const readForPrint = async (button) => {
      const content = page.waitForResponse((response) => { const url = new URL(response.url()); return url.pathname === `${OFFICE_PATH}/${saved.document.object_id}/content` && url.searchParams.get("version_id") === saved.version.version_id; });
      const pixels = page.waitForResponse((response) => new URL(response.url()).pathname === `${OFFICE_PATH}/${saved.document.object_id}/images/${image.attrs.assetId}/${image.attrs.versionId}`);
      await page.locator(button).click();
      for (const response of await Promise.all([content, pixels])) { expect(response.status()).toBe(200); expect(response.headers()["cache-control"]).toContain("no-store"); }
    };
    await readForPrint("#document-print"); await expect(page.locator("#print-submit")).toBeEnabled();
    await expect(page.locator("#print-paper")).toHaveValue(paper); await expect(page.locator("#print-orientation")).toHaveValue(orientation);
    await expect(page.locator("#print-page-description")).toContainText("links 40 mm");
    await page.locator("#print-paper").selectOption(paper === "a4" ? "letter" : "a4");
    await page.locator("#print-document-settings").click(); await expect(page.locator("#print-paper")).toHaveValue(paper);
    await readForPrint("#print-submit"); await expect.poll(() => prints[0]?.pdf?.length || 0, { timeout: 20_000 }).toBeGreaterThan(0);
    const [short, long] = paper === "a4" ? [595, 842] : [612, 792];
    expect(pdfPageCount(prints[0].pdf, orientation === "portrait" ? short : long, orientation === "portrait" ? long : short)).toBe(2);
    expectPdfStructure(prints[0].pdf, ["Figure", "Table", "TH", "TD"]);
    expect(await page.evaluate(() => {
      const sheet = [...document.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
      const rule = [...sheet.cssRules].find((entry) => entry.cssText.startsWith("@page office-document"));
      return Object.fromEntries(["top", "right", "bottom", "left"].map((side) => [side, rule.style.getPropertyValue(`margin-${side}`)]));
    })).toEqual({ top: "12mm", right: "25mm", bottom: "30mm", left: "40mm" });
    await page.locator("#print-close").click(); await expect(page.locator("#document-save")).toBeDisabled();
    expect((await officeContent(page, saved.document.object_id)).content).toEqual(document);
  });
}
