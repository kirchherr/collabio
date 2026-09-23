import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { officeEditor } from "./office-support.mjs";
import { selectCharacters } from "./character-helper.mjs";
import { openStyles, styleFixture, styleValues } from "./style-helper.mjs";

test("Office named style controls preview and shared update are reachable on desktop tablet and mobile", async ({ page }, testInfo) => {
  await styleFixture(page); await selectCharacters(page, 1, 2); await openStyles(page);
  const fits = async () => {
    expect(await page.locator("#style-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator("#style-close")).toBeInViewport();
    for (const id of ["style-choice", "style-name", "style-fontSize", "style-textAlign", "style-spacingAfter", "style-update", "style-remove", "style-cancel", "style-apply"]) {
      await page.locator(`#${id}`).scrollIntoViewIfNeeded(); await expect(page.locator(`#${id}`)).toBeInViewport();
    }
    await page.locator("#style-choice").scrollIntoViewIfNeeded();
  };
  await fits(); await page.screenshot({ path: `${ARTIFACT_DIR}/office-styles-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") { await page.setViewportSize({ width: 900, height: 900 }); await fits(); await page.screenshot({ path: `${ARTIFACT_DIR}/office-styles-tablet-chromium.png`, fullPage: true }); }
  await styleValues(page, { fontSize: 24 }); await page.locator("#style-update").click();
  await expect(page.locator("#style-dialog")).toBeHidden(); await expect(officeEditor(page)).toBeFocused();
});
