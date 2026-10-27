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
    for (const id of ["style-choice", "style-name", "style-fontFamily", "style-fontSize", "style-textColor", "style-letterSpacing", "style-textCase", "style-textAlign", "style-spacingAfter", "style-indentLeft", "style-indentRight", "style-specialIndent", "style-update", "style-remove", "style-cancel", "style-apply"]) {
      await page.locator(`#${id}`).scrollIntoViewIfNeeded(); await expect(page.locator(`#${id}`)).toBeInViewport();
    }
    await page.locator("#style-choice").scrollIntoViewIfNeeded();
  };
  await fits(); await page.screenshot({ path: `${ARTIFACT_DIR}/office-styles-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") { await page.setViewportSize({ width: 900, height: 900 }); await fits(); await page.screenshot({ path: `${ARTIFACT_DIR}/office-styles-tablet-chromium.png`, fullPage: true }); }
  await styleValues(page, { fontFamily: "mono", fontSize: 24, letterSpacing: "wide", textCase: "smallCaps", indentLeft: 54, indentRight: 36, specialIndent: "firstLine18" }); await page.locator("#style-update").click();
  await expect(page.locator("#style-dialog")).toBeHidden(); await expect(officeEditor(page)).toBeFocused();
  await expect(officeEditor(page).locator("p").first()).toHaveAttribute("data-office-letter-spacing", "wide");
  await expect(officeEditor(page).locator("p").first()).toHaveAttribute("data-office-text-case", "smallCaps");
  await expect(officeEditor(page).locator("p").first()).toHaveAttribute("data-office-indent-left", "54");
  await expect(officeEditor(page).locator("p").first()).toHaveAttribute("data-office-special-indent", "firstLine18");
});
