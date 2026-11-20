import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { newOfficeDraft, openOffice } from "./office-support.mjs";

test("Office structure controls remain reachable on desktop and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page); await newOfficeDraft(page, `Synthetic semantic responsive ${testInfo.project.name}`, { text: "Draft" });
  await page.locator("#semantic-options").click();
  await expect(page.locator("#semantic-dialog")).toBeVisible();
  for (const kind of ["field", "toc", "footnote", "source", "citation", "equation", "index"]) {
    await page.locator("#semantic-kind").selectOption(kind);
    await expect(page.locator("#semantic-kind")).toBeInViewport();
    await expect(page.locator("#semantic-apply")).toBeInViewport();
    expect(await page.locator("#semantic-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
  }
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-semantics-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#semantic-cancel").click(); await expect(page.locator("#semantic-dialog")).toBeHidden();
  verifyBrowser();
});
