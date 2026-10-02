import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";
import { createParagraphFixture, selectParagraphBlocks } from "./paragraph-helper.mjs";
import { characterDocument, openCharacters, expectCharacterStyle } from "./character-helper.mjs";

test("Office character dialog and styled content fit desktop tablet and mobile", async ({ page }, testInfo) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createParagraphFixture(page, `Zeichenformatierung ${testInfo.project.name}`, characterDocument());
  await openOffice(page); await openOfficeDocument(page, first.document.object_id);
  await selectParagraphBlocks(page, 0); await openCharacters(page);
  await page.locator("#character-size").selectOption("24"); await page.locator("#character-color").selectOption("purple");
  const fits = async () => {
    for (const id of ["character-size", "character-color", "character-apply", "character-reset", "character-cancel", "character-close"]) await expect(page.locator(`#${id}`)).toBeInViewport();
    expect(await page.locator("#character-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  };
  await fits(); await page.locator("#character-apply").click();
  await expectCharacterStyle(officeEditor(page).locator("span"), 24, "purple");
  await saveOffice(page, { objectId: first.document.object_id });
  await page.locator("#document-close").click(); await openOfficeDocument(page, first.document.object_id);
  await expectCharacterStyle(officeEditor(page).locator("span"), 24, "purple");
  await selectParagraphBlocks(page, 0); await openCharacters(page); await fits();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-character-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 }); await fits();
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-character-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#character-cancel").click(); await expect(page.locator("#document-save")).toBeDisabled(); verify();
});
