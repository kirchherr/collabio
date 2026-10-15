import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { officeEditor } from "./office-support.mjs";
import { selectCharacters } from "./character-helper.mjs";
import { listFixture, openListOptions } from "./list-helper.mjs";

test("Office list levels and numbering remain reachable on desktop tablet and mobile", async ({ page }, testInfo) => {
  await listFixture(page);
  await selectCharacters(page, 2, 2); await openListOptions(page);
  const fits = async () => {
    for (const id of ["list-close", "list-indent", "list-outdent", "list-start", "list-apply", "list-cancel"]) {
      await expect(page.locator(`#${id}`)).toBeInViewport();
    }
    expect(await page.locator("#list-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  };
  await fits();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-lists-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 }); await fits();
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-lists-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#list-indent").click();
  await expect(officeEditor(page).locator(":scope > ol ol")).toHaveCount(1);
  await expect(page.locator("#list-options")).toBeInViewport();
  await expect(officeEditor(page)).toBeFocused();
});
