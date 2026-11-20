import fs from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  ARTIFACT_DIR,
  BASE_URL,
  installContext,
  installResourceRoutes,
  monitorPage,
  resources,
  waitForWorkspace,
} from "./support.mjs";

test("Work remains readable and contained at the configured viewport", async ({ page }, testInfo) => {
  await installContext(page);
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await installResourceRoutes(
    page,
    Object.fromEntries(Object.keys(resources).map((key) => [key, { kind: "ready" }])),
  );

  await page.goto(`${BASE_URL}/work`);
  await waitForWorkspace(page, 7);

  const layout = await page.evaluate(() => {
    const duplicateIds = [...document.querySelectorAll("[id]")]
      .map((element) => element.id)
      .filter((id, index, ids) => ids.indexOf(id) !== index);
    const unnamedButtons = [...document.querySelectorAll("button")]
      .filter((button) => button.offsetParent !== null)
      .filter((button) => !(button.getAttribute("aria-label") || button.textContent?.trim()))
      .length;
    return {
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      duplicateIds,
      unnamedButtons,
    };
  });

  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(layout.duplicateIds).toEqual([]);
  expect(layout.unnamedButtons).toBe(0);
  fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, `work-${testInfo.project.name}.png`),
    fullPage: true,
  });
  assertClean();
});
