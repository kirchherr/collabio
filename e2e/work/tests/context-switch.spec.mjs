import { test, expect } from "@playwright/test";

import {
  BASE_URL,
  TENANT_ID,
  installContext,
  monitorPage,
  openView,
  resources,
  responseBody,
  waitForWorkspace,
} from "./support.mjs";

test("Context switch discards delayed prior-tenant reads and write capabilities in every Work panel", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  const nextTenant = "tenant-work-e2e-alternate";
  let knowledgeCalls = 0;
  let releaseOldResponse;
  let signalOldRequest;
  const oldResponseGate = new Promise((resolve) => { releaseOldResponse = resolve; });
  const oldRequestStarted = new Promise((resolve) => { signalOldRequest = resolve; });
  await installContext(page);
  for (const [key, resource] of Object.entries(resources)) {
    await page.route(`**${resource.path}`, async (route) => {
      const tenant = route.request().headers()["x-tenant-id"];
      if (key === "knowledge" && tenant === TENANT_ID && ++knowledgeCalls === 2) {
        signalOldRequest();
        await oldResponseGate;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...responseBody(resource, tenant === TENANT_ID ? resource.items : []),
          tenant_id: tenant,
          ...(key === "knowledge" ? { can_write: tenant === TENANT_ID } : {}),
        }),
      });
    });
  }

  try {
    await page.goto(`${BASE_URL}/work`, { waitUntil: "domcontentloaded" });
    await waitForWorkspace(page, 7);
    await openView(page, "knowledge");
    await expect(page.locator("#knowledge-create")).toBeVisible();
    await expect(page.locator("#knowledge-list")).toContainText(resources.knowledge.token);

    await page.locator("#refresh-button").click();
    await oldRequestStarted;
    await page.locator("#context-button").click();
    await page.locator("#tenant-id").fill(nextTenant);
    await page.locator("#user-id").fill("work-alternate-user-e2e");
    await page.locator("#role-ids").fill("reader");
    await page.locator('#context-form button[type="submit"]').click();
    await waitForWorkspace(page, 7);
    await expect(page.locator("#tenant-label")).toHaveText(nextTenant);
    await expect(page.locator("#knowledge-create")).toBeHidden();

    const oldTokens = Object.entries(resources)
      .filter(([key]) => key !== "timeApprovals")
      .map(([, resource]) => resource.token);
    await page.evaluate((tokens) => {
      window.contextSwitchLeak = false;
      const inspect = () => {
        const staleContent = tokens.some((token) => document.querySelector(".app-main").textContent.includes(token));
        const staleCapability = !document.querySelector("#knowledge-create").hidden;
        window.contextSwitchLeak ||= staleContent || staleCapability;
      };
      inspect();
      new MutationObserver(inspect).observe(document.querySelector(".app-main"), {
        subtree: true, childList: true, attributes: true, characterData: true,
      });
    }, oldTokens);

    const delayedResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === resources.knowledge.path &&
      response.request().headers()["x-tenant-id"] === TENANT_ID,
    );
    releaseOldResponse();
    await (await delayedResponse).finished();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));

    expect(await page.evaluate(() => window.contextSwitchLeak)).toBe(false);
    for (const token of oldTokens) {
      await expect(page.locator(".app-main")).not.toContainText(token);
    }
    await expect(page.locator("#knowledge-list")).toContainText("Keine Wissensartikel im Filter.");
    await expect(page.locator("#knowledge-create")).toBeHidden();
    await expect(page.locator("#refresh-button")).toBeEnabled();
    assertClean();
  } finally {
    releaseOldResponse();
  }
});
