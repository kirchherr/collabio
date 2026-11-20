import { test, expect } from "@playwright/test";

import {
  BLOCKED_BASE_URL,
  HTTP_FORBIDDEN_CONSOLE_ERROR,
  HTTP_LOCKED_CONSOLE_ERROR,
  HTTP_NOT_FOUND_CONSOLE_ERROR,
  installContext,
  monitorPage,
  resources,
  waitForWorkspace,
} from "./support.mjs";

test("pilot-scoped Work APIs remain fail-closed when the runtime switch is disabled", async ({ page }) => {
  await installContext(page);
  const assertClean = monitorPage(page, {
    baseUrls: [BLOCKED_BASE_URL],
    expectedConsoleErrors: [
      ...Array(4).fill(HTTP_LOCKED_CONSOLE_ERROR),
      HTTP_FORBIDDEN_CONSOLE_ERROR,
      HTTP_NOT_FOUND_CONSOLE_ERROR,
    ],
  });
  const statuses = new Map();
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    const resource = Object.entries(resources).find(([, definition]) => definition.path === path);
    if (resource) {
      statuses.set(resource[0], response.status());
    }
  });

  await page.goto(`${BLOCKED_BASE_URL}/work`);
  await waitForWorkspace(page, 1);
  await expect(page.locator("#sync-line")).toContainText("6 gesperrt");
  await expect(page.locator(".availability-item")).toHaveCount(5);
  await expect(page.locator(".availability-item").first()).toContainText(
    "Pilot-Laufzeit geschlossen",
  );
  expect(Object.fromEntries(statuses)).toEqual({
    tasks: 423,
    taskActivities: 423,
    timeEntries: 423,
    timeApprovals: 423,
    tickets: 404,
    knowledge: 200,
    crm: 403,
  });
  assertClean();
});
