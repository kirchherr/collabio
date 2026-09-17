import { test, expect } from "@playwright/test";

import {
  BASE_URL,
  availabilityItem,
  installContext,
  installResourceRoutes,
  monitorPage,
  openView,
  resources,
  waitForWorkspace,
} from "./support.mjs";

for (const [key, resource] of Object.entries(resources)) {
  for (const kind of ["ready", "empty", "blocked", "unavailable"]) {
    test(`${resource.label} degrades independently as ${kind}`, async ({ page }) => {
      await installContext(page);
      const assertClean = monitorPage(page, BASE_URL);
      const states = { [key]: { kind } };
      if (key === "timeApprovals" && kind === "ready") {
        states.timeEntries = { kind: "ready" };
      }
      const calls = await installResourceRoutes(page, states);

      await page.goto(`${BASE_URL}/work`);
      await waitForWorkspace(page, ["ready", "empty"].includes(kind) ? 7 : 6);
      expect(calls[key]).toBe(1);

      if (kind === "ready") {
        await openView(page, resource.view);
        await expect(page.locator(`[data-view-panel="${resource.view}"]`)).toContainText(resource.token);
      } else if (kind === "empty") {
        await expect(availabilityItem(page, resource.group)).toContainText("Bereit");
      } else {
        const reason = `synthetic_${key}_${kind}`;
        await expect(availabilityItem(page, resource.group)).toContainText(reason);
        if (kind === "blocked") {
          await expect(page.locator("#sync-line")).toContainText("1 gesperrt");
        } else {
          await expect(page.locator("#sync-line")).not.toContainText("gesperrt");
        }
        if (resource.errorSelector) {
          await openView(page, resource.view);
          await expect(page.locator(resource.errorSelector)).toContainText(
            kind === "blocked" ? "Bereich gesperrt" : "Bereich nicht verfuegbar",
          );
        }
      }

      assertClean();
    });
  }
}
