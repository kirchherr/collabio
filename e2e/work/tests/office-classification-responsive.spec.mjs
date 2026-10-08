import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { newOfficeDraft, openOffice, saveOffice } from "./office-support.mjs";

test("Office classification is versioned, responsive and printed", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, `Synthetic classification ${testInfo.project.name}`, {
    text: "Versioned information classification",
    classification: "confidential",
  });
  await expect(page.locator("#document-classification")).toHaveValue("confidential");
  await expect(page.locator("#document-classification-field")).toHaveAttribute("data-classification", "confidential");
  const first = await saveOffice(page);
  expect(first.document.information_classification).toBe("confidential");
  expect(first.version.information_classification).toBe("confidential");

  await page.locator("#document-classification").selectOption("restricted");
  await expect(page.locator("#document-save")).toBeEnabled();
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(second.document.information_classification).toBe("restricted");
  expect(second.version.information_classification).toBe("restricted");

  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-classification")).toHaveText("Streng vertraulich");
  await expect(page.locator("#print-preview .office-print-classification")).toHaveAttribute(
    "data-classification",
    "restricted",
  );
  await expect(page.locator("#print-version")).toContainText("Streng vertraulich");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-classification-${testInfo.project.name}.png`, fullPage: true });
  verifyBrowser();
});
