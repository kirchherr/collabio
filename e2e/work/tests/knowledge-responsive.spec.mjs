import path from "node:path";

import { test, expect } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { approveKnowledgeDraft, executeKnowledgeDraft, newKnowledgeDraft, openKnowledge } from "./knowledge-support.mjs";

test("Knowledge editor, evidence and explicit confirmation fit the configured viewport", async ({ page }, testInfo) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  await newKnowledgeDraft(page, `Synthetic responsive ${testInfo.project.name} ${Date.now()}`, "Synthetic responsive body ".repeat(12));
  await approveKnowledgeDraft(page);
  const layout = await page.locator("#knowledge-dialog").evaluate((dialog) => {
    const bounds = dialog.getBoundingClientRect();
    return {
      left: bounds.left,
      right: bounds.right,
      clientWidth: dialog.clientWidth,
      scrollWidth: dialog.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });
  expect(layout.left).toBeGreaterThanOrEqual(0);
  expect(layout.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  await page.locator("#knowledge-confirm").scrollIntoViewIfNeeded();
  await expect(page.locator("#knowledge-confirm")).toBeInViewport();
  await executeKnowledgeDraft(page);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, `work-knowledge-${testInfo.project.name}.png`), fullPage: true });
  assertClean();
});
