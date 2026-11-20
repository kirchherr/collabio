import { writeFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { BLOCKED_BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { OFFICE_PATH, OFFICE_READER_ID, officeContent, officeEditor, openOffice, openOfficeDocument,
  saveOffice, setOfficeAcl, openOfficeComparison, loadOfficeComparison } from "./office-support.mjs";
import { styleFixture } from "./style-helper.mjs";
import { installPrintProbe, pdfPageCount, expectPdfStructure } from "./office-print-support.mjs";
import { openReuse, submitReuse, expectReuseDraft, openReuseHistory } from "./office-reuse-support.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const running = () => ({ header: 'RUNNING-HEADER "quoted" \\ <literal>', footer: "RUNNING-FOOTER internal", numbering: "pageOfPages" });
const firstPageRunning = () => ({ ...running(), firstPage: { header: "FIRST-PAGE COVER", footer: "FIRST-PAGE ONLY", showNumber: false } });
async function openSettings(page) {
  await page.locator("#page-options").click(); await expect(page.locator("#page-dialog")).toBeVisible();
  await page.locator("#page-running-details summary").click();
}
async function choose(page, value = running()) {
  await page.locator("#page-header").fill(value.header); await page.locator("#page-footer").fill(value.footer);
  await page.locator("#page-numbering").selectOption(value.numbering);
  if (value.firstPage) {
    await page.locator("#page-first-different").check();
    await page.locator("#page-first-header").fill(value.firstPage.header);
    await page.locator("#page-first-footer").fill(value.firstPage.footer);
    await page.locator("#page-first-number").setChecked(value.firstPage.showNumber);
  }
}
async function apply(page, value = running()) {
  await openSettings(page); await choose(page, value); await page.locator("#page-apply").click();
  await expect(page.locator("#page-dialog")).toBeHidden(); await expect(officeEditor(page)).toBeFocused();
}
async function cssContents(page) {
  return page.evaluate(() => {
    const sheet = [...document.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
    return [...sheet.cssRules].filter((entry) => entry.cssText.startsWith("@page office-document"))
      .flatMap((rule) => [...rule.cssRules].map((entry) => entry.style.content));
  });
}
const probes = new WeakMap();
async function printSaved(page, saved, name) {
  if (!probes.has(page)) probes.set(page, await installPrintProbe(page, { pdfName: name + ".capture.pdf" }));
  const calls = probes.get(page), index = calls.length;
  const path = `${OFFICE_PATH}/${saved.document.object_id}/content`;
  for (const button of ["#document-print", "#print-submit"]) {
    const response = page.waitForResponse((response) => { const url = new URL(response.url()); return url.pathname === path && url.searchParams.get("version_id") === saved.version.version_id; });
    await page.locator(button).click(); const read = await response;
    expect(read.status()).toBe(200); expect(read.headers()["cache-control"]).toContain("no-store");
    if (button === "#document-print") await expect(page.locator("#print-submit")).toBeEnabled();
  }
  await expect.poll(() => calls[index]?.pdf?.length || 0, { timeout: 20_000 }).toBeGreaterThan(0);
  await expect.poll(() => cssContents(page)).toEqual(["none", "none", "none", "none"]);
  await page.locator("#print-close").click();
  await writeFile(`${ARTIFACT_DIR}/${name}`, calls[index].pdf);
  return calls[index].pdf;
}

test("Office running text validates preview cancel no-op and isolated typing undo", async ({ page }, testInfo) => {
  const first = await styleFixture(page, { type: "doc", content: [p("Running text body")] });
  await openSettings(page); await page.locator("#page-apply").click(); await expect(page.locator("#page-status")).toContainText("Keine Änderung");
  await choose(page); await page.locator("#page-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).click(); await page.keyboard.press("Control+End"); await page.keyboard.press("Control+b");
  await openSettings(page); await choose(page); await page.locator("#page-header").fill("x".repeat(65));
  await expect(page.locator("#page-apply")).toBeDisabled(); await choose(page);
  await page.locator("#page-top").fill("15"); await expect(page.locator("#page-apply")).toBeDisabled();
  await page.locator("#page-top").fill("18"); await page.locator("#page-bottom").fill("15");
  await expect(page.locator("#page-apply")).toBeDisabled(); await page.locator("#page-bottom").fill("18");
  await expect(page.locator("#page-running-preview")).toContainText('RUNNING-HEADER "quoted"');
  await expect(page.locator("#page-running-preview")).toContainText("Seite 1 von 3");
  expect(await page.locator("#page-dialog").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.locator("#page-numbering").scrollIntoViewIfNeeded();
  await expect(page.locator("#page-apply")).toBeInViewport(); await expect(page.locator("#page-cancel")).toBeInViewport();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-running-text-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#page-apply").click(); await expect(officeEditor(page)).toBeFocused(); await page.keyboard.type("X");
  await expect(officeEditor(page).locator("strong")).toHaveText("X"); await page.keyboard.press("Control+z");
  await expect(officeEditor(page)).toHaveText("Running text body"); await page.keyboard.press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled(); await page.keyboard.press("Control+Shift+z");
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.content.attrs.running).toEqual(running()); expect(saved.content.content).toEqual(first.content.content);
});

test("Office running text reset history comparison and independent copies preserve exact metadata", async ({ page }) => {
  const explicitPage = { paper: "a4", orientation: "portrait", margins: { top: 18, right: 18, bottom: 18, left: 18 } };
  const first = await styleFixture(page, { type: "doc", attrs: { page: explicitPage }, content: [p("Body"), { type: "pageBreak" }, p("Last")] });
  await apply(page); const custom = await saveOffice(page, { objectId: first.document.object_id });
  expect(custom.content.attrs.page).toEqual(explicitPage);
  await openSettings(page); await page.locator("#page-running-reset").click(); await page.locator("#page-apply").click();
  const reset = await saveOffice(page, { objectId: first.document.object_id }); expect(reset.content).toEqual(first.content);
  expect((await officeContent(page, first.document.object_id, { versionId: custom.version.version_id })).content).toEqual(custom.content);
  await openOfficeComparison(page); await loadOfficeComparison(page, first.document.object_id, custom.version.version_id, reset.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("Kopf-/Fußzeilen und Seitenzahlen");
  await expect(page.locator("#compare-results")).toContainText("RUNNING-HEADER"); await page.locator("#compare-close").click();
  await openReuseHistory(page, custom); await expect(page.locator("#page-options")).toBeDisabled();
  await openReuse(page, custom, "Independent running text"); await submitReuse(page, custom); await expectReuseDraft(page, "Independent running text");
  const copied = await saveOffice(page); expect(copied.content).toEqual(custom.content);
  expect(copied.document.object_id).not.toBe(first.document.object_id);

  // Reset geometry, then edit running text: both independent intents must survive.
  await openSettings(page); await page.locator("#page-reset").click();
  await page.locator("#page-header").fill("Changed after page reset"); await page.locator("#page-apply").click();
  const pageReset = await saveOffice(page, { objectId: copied.document.object_id });
  expect(pageReset.content.attrs.page).toBeUndefined();
  expect(pageReset.content.attrs.running.header).toBe("Changed after page reset");

  // Explicit empty metadata also resets when geometry is edited afterwards.
  const empty = await styleFixture(page, { type: "doc", attrs: { page: explicitPage,
    running: { header: "", footer: "", numbering: "none" } }, content: [p("Empty metadata reset")] });
  await openSettings(page); await page.locator("#page-running-reset").click();
  await page.locator("#page-left").fill("19"); await page.locator("#page-apply").click();
  const changedPage = await saveOffice(page, { objectId: empty.document.object_id });
  expect(changedPage.content.attrs.running).toBeUndefined();
  expect(changedPage.content.attrs.page.margins.left).toBe(19);
});

test("Office running text read-only and changed-context boundaries clear literal inputs", async ({ page, context }) => {
  const first = await styleFixture(page, { type: "doc", attrs: { running: running() }, content: [p("Body")] });
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage(); await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id); await expect(reader.locator("#page-options")).toBeDisabled();
  await openSettings(page); await expect(page.locator("#page-header")).toHaveValue(running().header);
  await page.evaluate(() => { document.querySelector("#user-id").value = "work-assignee-e2e"; document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await expect(page.locator("#page-dialog")).toBeHidden(); await expect(page.locator("#page-header")).toHaveValue("");
  await expect(page.locator("#page-running-preview")).toBeEmpty(); expect(await cssContents(page)).toEqual(["none", "none", "none", "none"]);
});

test("Office running text automatic pagination and reset print leave no stale margin content", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const first = await styleFixture(page, { type: "doc", attrs: { running: { ...running(), numbering: "page" } }, content: Array.from({ length: 36 }, (_, n) => p(`AUTO-BODY-${n + 1} ${"Saved text with automatic pagination. ".repeat(3)}`)) });
  const pdf = await printSaved(page, first, `office-running-auto-${testInfo.project.name}.pdf`);
  expect(pdfPageCount(pdf, 595, 842)).toBeGreaterThan(1);
  await openSettings(page); await page.locator("#page-running-reset").click(); await page.locator("#page-apply").click();
  const reset = await saveOffice(page, { objectId: first.document.object_id }); expect(reset.content.attrs?.running).toBeUndefined();
  // Same browser document, same stylesheet, new print call: prove sensitive margin cleanup.
  await printSaved(page, reset, `office-running-reset-${testInfo.project.name}.pdf`);
  await expect(page.locator("#document-save")).toBeDisabled(); expect(await cssContents(page)).toEqual(["none", "none", "none", "none"]);
});

test("Office first-page running text previews saves reopens resets and copies exact metadata", async ({ page }, testInfo) => {
  const first = await styleFixture(page, { type: "doc", content: [p("Cover"), { type: "pageBreak" }, p("Following")] });
  await openSettings(page); await choose(page, firstPageRunning());
  await expect(page.locator("#page-running-preview")).toContainText("FIRST-PAGE COVER");
  await expect(page.locator("#page-running-preview")).not.toContainText("Seite 1");
  await expect(page.locator("#page-running-preview-following")).toContainText("RUNNING-HEADER");
  await expect(page.locator("#page-running-preview-following")).toContainText("Seite 2 von 3");
  await page.locator("#page-first-number").scrollIntoViewIfNeeded();
  expect(await page.locator("#page-first-number").evaluate((element) => element.getBoundingClientRect().width <= 24)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-first-page-dialog-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#page-apply").click();
  const custom = await saveOffice(page, { objectId: first.document.object_id });
  expect(custom.content.attrs.running).toEqual(firstPageRunning());
  await openSettings(page); await expect(page.locator("#page-first-different")).toBeChecked();
  await expect(page.locator("#page-first-header")).toHaveValue("FIRST-PAGE COVER");
  await page.locator("#page-cancel").click();
  await openReuse(page, custom, "Independent first page"); await submitReuse(page, custom);
  await expectReuseDraft(page, "Independent first page");
  const copied = await saveOffice(page); expect(copied.content).toEqual(custom.content);
  await openSettings(page); await page.locator("#page-running-reset").click(); await page.locator("#page-apply").click();
  const reset = await saveOffice(page, { objectId: copied.document.object_id });
  expect(reset.content.attrs?.running).toBeUndefined();
  expect((await officeContent(page, first.document.object_id, { versionId: custom.version.version_id })).content).toEqual(custom.content);
});

test("Office unsupported running print refuses output and clears the prepared body", async ({ page }) => {
  await styleFixture(page, { type: "doc", attrs: { running: running() }, content: [p("Protected running body")] });
  await page.evaluate(() => {
    const sheet = [...document.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
    const rule = [...sheet.cssRules].find((entry) => entry.cssText.startsWith("@page office-document"));
    while (rule.cssRules.length) rule.deleteRule(0);
    window.unexpectedRunningPrint = false; window.print = () => { window.unexpectedRunningPrint = true; };
  });
  await page.locator("#document-print").click(); await expect(page.locator("#print-submit")).toBeEnabled();
  await page.locator("#print-submit").click(); await expect(page.locator("#print-status")).toContainText("Ihr Browser unterstützt");
  await expect(page.locator("#office-print-root")).toBeEmpty(); await expect(page.locator("body")).not.toHaveClass(/office-print-ready/);
  expect(await page.evaluate(() => window.unexpectedRunningPrint)).toBe(false);
});

for (const paper of ["a4", "letter"]) for (const orientation of ["portrait", "landscape"]) {
  test(`Office running text actual ${paper} ${orientation} PDF repeats literal headers footers and page totals`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const row = (type, a, b) => ({ type: "tableRow", content: [a, b].map((text) => ({ type, attrs: { colspan: 1, rowspan: 1 }, content: [p(text)] })) });
    const content = { type: "doc", attrs: {
      page: { paper, orientation, margins: { top: 16, bottom: 16, left: 50, right: 50 } },
      running: { header: 'RUNNING-HEADER "\\<>& ' + "H".repeat(42), footer: "RUNNING-FOOTER " + "F".repeat(49), numbering: "pageOfPages" },
    }, content: [p("RUNNING-BODY-ONE"), { type: "pageBreak" },
      { type: "table", content: [row("tableHeader", "RUNNING-BODY-TWO", "Column"), row("tableCell", "Cell", "Data")] },
      { type: "pageBreak" }, p("RUNNING-BODY-THREE")] };
    const saved = await styleFixture(page, content);
    const pdf = await printSaved(page, saved, `office-running-${paper}-${orientation}-${testInfo.project.name}.pdf`);
    const [short, long] = paper === "a4" ? [595, 842] : [612, 792];
    expect(pdfPageCount(pdf, orientation === "portrait" ? short : long, orientation === "portrait" ? long : short)).toBe(3);
    expectPdfStructure(pdf, ["Table", "TH", "TD"]);
    expect((await officeContent(page, saved.document.object_id)).content).toEqual(content);
  });
}

test("Office first-page running text actual PDF differs and hides only its page number", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const content = { type: "doc", attrs: {
    page: { paper: "a4", orientation: "portrait", margins: { top: 18, bottom: 18, left: 35, right: 35 } },
    running: firstPageRunning(),
  }, content: [p("FIRST-PAGE-BODY"), { type: "pageBreak" }, p("SECOND-PAGE-BODY"),
    { type: "pageBreak" }, p("THIRD-PAGE-BODY")] };
  const saved = await styleFixture(page, content);
  const pdf = await printSaved(page, saved, `office-running-first-page-${testInfo.project.name}.pdf`);
  expect(pdfPageCount(pdf, 595, 842)).toBe(3);
  expect((await officeContent(page, saved.document.object_id)).content).toEqual(content);
  await openSettings(page); await page.locator("#page-first-number").check(); await page.locator("#page-apply").click();
  const numbered = await saveOffice(page, { objectId: saved.document.object_id });
  expect(numbered.content.attrs.running.firstPage.showNumber).toBe(true);
  const numberedPdf = await printSaved(page, numbered, `office-running-first-page-numbered-${testInfo.project.name}.pdf`);
  expect(pdfPageCount(numberedPdf, 595, 842)).toBe(3);
});
