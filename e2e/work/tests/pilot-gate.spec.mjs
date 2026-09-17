import { test, expect } from "@playwright/test";

import {
  BLOCKED_BASE_URL,
  installContext,
  monitorPage,
  resources,
  waitForWorkspace,
} from "./support.mjs";

test("the ordinary Work API remains fail-closed without pilot authorization", async ({ page }) => {
  await installContext(page);
  const assertClean = monitorPage(page, BLOCKED_BASE_URL);
  const statuses = new Map();
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    const resource = Object.entries(resources).find(([, definition]) => definition.path === path);
    if (resource) {
      statuses.set(resource[0], response.status());
    }
  });

  await page.goto(`${BLOCKED_BASE_URL}/work`);
  await waitForWorkspace(page, 0);
  await expect(page.locator("#sync-line")).toContainText("7 gesperrt");
  await expect(page.locator(".availability-item")).toHaveCount(5);
  await expect(page.locator(".availability-item").first()).toContainText(
    "Pilot-Laufzeit geschlossen",
  );
  expect(Object.fromEntries(statuses)).toEqual(
    Object.fromEntries(Object.keys(resources).map((key) => [key, 423])),
  );
  assertClean();
});
