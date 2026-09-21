import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import {
  FORMAT_IDS, PARAGRAPH_FORMAT, chooseParagraphFormat, createParagraphFixture, expectParagraphStyle,
  openParagraphDialog, paragraph, paragraphBlocks, selectParagraphBlocks,
} from "./paragraph-helper.mjs";

async function expectParagraphDialogFits(page) {
  for (const id of [...Object.values(FORMAT_IDS), "paragraph-selection", "paragraph-apply", "paragraph-reset", "paragraph-cancel", "paragraph-close"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await page.locator("#paragraph-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("Office paragraph formatting and saved content remain reachable on desktop tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createParagraphFixture(page, `Paragraph layout ${testInfo.project.name}`, { type: "doc", content: [
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Absatzformatierung" }] },
    paragraph("Lesbare Abstände für Café 😀 und klare Ausrichtung. Der gespeicherte Text bleibt unverändert."),
  ] });
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0, 1);
  await openParagraphDialog(page, 2);
  await chooseParagraphFormat(page, PARAGRAPH_FORMAT);
  await expectParagraphDialogFits(page);
  await page.locator("#paragraph-apply").click();
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  await expectParagraphStyle(paragraphBlocks(page).last(), PARAGRAPH_FORMAT);
  await expect(officeEditor(page)).toBeInViewport();
  await saveOffice(page, { objectId: first.document.object_id });
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await expectParagraphStyle(paragraphBlocks(page).last(), PARAGRAPH_FORMAT);
  await selectParagraphBlocks(page, 0, 1);
  await openParagraphDialog(page, 2);
  await expectParagraphDialogFits(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-paragraph-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectParagraphDialogFits(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-paragraph-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#paragraph-cancel").click();
  await expect(officeEditor(page)).toBeFocused();
  await expect(page.locator("#document-save")).toBeDisabled();
  verifyBrowser();
});
