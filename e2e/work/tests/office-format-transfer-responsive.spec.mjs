import { expect, test } from "@playwright/test";
import { ARTIFACT_DIR } from "./support.mjs";
import { officeEditor } from "./office-support.mjs";
import { selectParagraphBlocks } from "./paragraph-helper.mjs";
import { captureSample, transfer, transferFixture } from "./format-transfer-helper.mjs";

test("Office format transfer remains usable on desktop tablet and mobile", async ({ page }, testInfo) => {
  await transferFixture(page);
  await captureSample(page);
  await selectParagraphBlocks(page, 1);
  await transfer(page, "both");
  const fits = async () => {
    await expect(page.locator("#format-transfer")).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(officeEditor(page).locator("h2 span")).toHaveAttribute("data-office-font-size", "24");
  };
  await fits();
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-format-transfer-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await fits();
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-format-transfer-tablet-chromium.png`, fullPage: true });
  }
});
