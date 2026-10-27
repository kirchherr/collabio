import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  ARTIFACT_DIR, BASE_URL, BLOCKED_BASE_URL, HTTP_FORBIDDEN_CONSOLE_ERROR,
  HTTP_NOT_FOUND_CONSOLE_ERROR, HTTP_UNAVAILABLE_CONSOLE_ERROR, monitorPage, openView, waitForWorkspace,
} from "./support.mjs";
import {
  CRM_EMPTY_ID, CRM_MAIN_ID, CRM_MAIN_NAME, CRM_OTHER_ID, CRM_READER_HEADERS, closeCrm,
  crmFeatures, crmWorkspacePath, expectCrmCleared, holdCrmResponse, openCrm, readCrm,
  setCrmAccountReadAcl, setCrmFeatures, watchStaleCrmContent,
} from "./crm-support.mjs";

test("CRM details read real PostgreSQL children, filter other accounts and redact inaccessible relations", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  const crmRequests = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/v1/crm/")) crmRequests.push(pathname);
  });
  await openCrm(page);
  await expect(page.locator("[data-crm-detail]")).toHaveCount(3);
  const detail = await readCrm(page);
  expect(detail.account.display_name).toBe(CRM_MAIN_NAME);
  expect(detail.contacts.map((item) => item.object_id)).toEqual(["crm-contact-work-e2e-main"]);
  expect(detail.activities.map((item) => item.object_id)).toEqual([
    "crm-activity-work-e2e-main", "crm-activity-work-e2e-linked", "crm-activity-work-e2e-redacted",
  ]);
  expect(detail.activities[1].account_object_id).toBeNull();
  expect(detail.activities[1].contact_object_id).toBe("crm-contact-work-e2e-main");
  expect(detail.activities[2].contact_object_id).toBeNull();
  expect(detail.notes).toHaveLength(1);
  expect(detail.notes[0].contact_object_id).toBeNull();
  expect(detail.notes[0].activity_object_id).toBeNull();
  expect(detail.counts).toEqual({ contact_count: 1, activity_count: 3, note_count: 1, total_object_count: 6 });
  for (const forbidden of ["crm-contact-work-e2e-hidden", "crm-activity-work-e2e-hidden", CRM_OTHER_ID, "note_body"]) {
    expect(JSON.stringify(detail)).not.toContain(forbidden);
    await expect(page.locator("#crm-detail-dialog")).not.toContainText(forbidden);
  }
  await expect(page.locator("#crm-detail-contacts")).toContainText("synthetic.crm@work-e2e.invalid");
  await expect(page.locator("#crm-detail-contacts")).toContainText("+49 000 0000");
  await expect(page.locator("#crm-detail-contacts")).toContainText("<img src=https://outside.invalid/x");
  await expect(page.locator("#crm-detail-activities")).toContainText("<script>window.crmUnsafe=true</script>");
  await expect(page.locator("#crm-detail-dialog script, #crm-detail-dialog img, #crm-detail-dialog a")).toHaveCount(0);
  await expect(page.locator("#crm-detail-dialog")).not.toContainText("Synthetic CRM note metadata only");
  expect(await page.evaluate(() => window.crmUnsafe)).toBeUndefined();
  expect(crmRequests).toEqual(["/v1/crm/accounts", crmWorkspacePath(CRM_MAIN_ID)]);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, "work-crm-detail-complete.png"), fullPage: true });
  assertClean();
});

test("an authorized CRM account with no children shows independent empty contact and activity states", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openCrm(page);
  const detail = await readCrm(page, CRM_EMPTY_ID);
  expect(detail.counts).toEqual({ contact_count: 0, activity_count: 0, note_count: 0, total_object_count: 1 });
  await expect(page.locator("#crm-detail-contacts")).toHaveText("Keine freigegebenen Kontakte zu diesem Konto.");
  await expect(page.locator("#crm-detail-activities")).toHaveText("Keine freigegebenen Aktivitaeten zu diesem Konto.");
  await closeCrm(page);
  await expect(page.locator(`[data-crm-detail="${CRM_MAIN_ID}"]`)).toBeEnabled();
  assertClean();
});

test("missing CRM ACLs, forged readable IDs, a foreign tenant and the closed pilot cannot expose account details", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openCrm(page);
  const read = (id, headers = {}, baseUrl = BASE_URL) => page.request.get(`${baseUrl}${crmWorkspacePath(id)}`, {
    headers: { ...CRM_READER_HEADERS, ...headers },
  });
  const absent = await read("crm-account-work-e2e-missing");
  expect(absent.status()).toBe(404);
  const genericMissing = await absent.json();
  const hidden = await read("crm-account-work-e2e-hidden", {
    "X-Readable-Object-Ids": "crm-account-work-e2e-hidden,crm-contact-work-e2e-hidden",
  });
  expect(hidden.status()).toBe(404);
  expect(await hidden.json()).toEqual(genericMissing);
  const foreign = await read(CRM_MAIN_ID, { "X-Tenant-Id": "tenant-work-e2e-foreign" });
  expect(foreign.status()).toBe(403);
  expect(await foreign.text()).not.toContain(CRM_MAIN_NAME);
  const pilotBlocked = await read(CRM_MAIN_ID, {}, BLOCKED_BASE_URL);
  expect(pilotBlocked.status()).toBe(403);
  expect(await pilotBlocked.text()).not.toContain(CRM_MAIN_NAME);
  await expect(page.locator('[data-crm-detail="crm-account-work-e2e-hidden"]')).toHaveCount(0);
  assertClean();
});

test("revoking the CRM account ACL clears previously visible details on refresh", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL], expectedConsoleErrors: [HTTP_NOT_FOUND_CONSOLE_ERROR] });
  await openCrm(page);
  await readCrm(page);
  try {
    await setCrmAccountReadAcl(page, "revoked");
    const denied = await readCrm(page, CRM_MAIN_ID, { refresh: true, status: 404 });
    expect(denied).toEqual({ detail: "CRM account workspace not found" });
    await expectCrmCleared(page);
    await expect(page.locator("#crm-detail-title")).not.toHaveText(CRM_MAIN_NAME);
    await expect(page.locator("#crm-detail-status")).toHaveText("Die Kontodetails sind nicht verfuegbar oder nicht freigegeben.");
  } finally {
    await setCrmAccountReadAcl(page, "active");
  }
  await readCrm(page, CRM_MAIN_ID, { refresh: true });
  assertClean();
});

test("a disabled CRM contacts feature blocks the entire detail response and recovers after exact fixture restoration", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL], expectedConsoleErrors: [HTTP_FORBIDDEN_CONSOLE_ERROR] });
  await openCrm(page);
  await readCrm(page);
  const originalFeatures = await crmFeatures(page);
  expect(originalFeatures["crm_erp.crm.contacts"]).toBe(true);
  try {
    await setCrmFeatures(page, { ...originalFeatures, "crm_erp.crm.contacts": false });
    await readCrm(page, CRM_MAIN_ID, { refresh: true, status: 403 });
    await expectCrmCleared(page);
    await expect(page.locator("#crm-detail-status")).toHaveText("Die Kontodetails sind nicht verfuegbar oder nicht freigegeben.");
  } finally {
    await setCrmFeatures(page, originalFeatures);
  }
  expect(await crmFeatures(page)).toEqual(originalFeatures);
  await readCrm(page, CRM_MAIN_ID, { refresh: true });
  assertClean();
});

test("a scoped PostgreSQL CRM failure clears details, supports retry and leaves other Work panels usable", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL], expectedConsoleErrors: [HTTP_UNAVAILABLE_CONSOLE_ERROR] });
  await openCrm(page);
  await readCrm(page);
  await page.route(`**${crmWorkspacePath(CRM_MAIN_ID)}`, (route) => route.continue({
    headers: { ...route.request().headers(), "X-Work-E2E-Fail-CRM": "1" },
  }), { times: 1 });
  const failed = await readCrm(page, CRM_MAIN_ID, { refresh: true, status: 503 });
  expect(failed).toEqual({ detail: "CRM account workspace unavailable" });
  await expectCrmCleared(page);
  await expect(page.locator("#crm-detail-status")).toHaveText("Die Kontodetails konnten nicht geladen werden. Bitte versuchen Sie es erneut.");
  await expect(page.locator("#crm-detail-dialog")).not.toContainText("database failure");
  await readCrm(page, CRM_MAIN_ID, { refresh: true });
  await closeCrm(page);
  for (const [view, selector, text] of [
    ["tasks", "#task-list", "Synthetic E2E task"],
    ["time", "#time-entry-list", "project:synthetic-state"],
    ["tickets", "#ticket-list", "Synthetic E2E ticket"],
    ["knowledge", "#knowledge-list", "Synthetic E2E knowledge"],
  ]) {
    await openView(page, view);
    await expect(page.locator(selector)).toContainText(text);
  }
  assertClean();
});

test("closing CRM details and selecting another account suppresses the previous delayed real response", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openCrm(page);
  const delayed = await holdCrmResponse(page);
  try {
    await page.locator(`[data-crm-detail="${CRM_MAIN_ID}"]`).click();
    await delayed.ready;
    await expect(page.locator("#crm-detail-status")).toContainText("werden geladen");
    await expectCrmCleared(page);
    await closeCrm(page);
    await watchStaleCrmContent(page);
    const current = await readCrm(page, CRM_OTHER_ID);
    expect(current.contacts.map((contact) => contact.object_id)).toEqual(["crm-contact-work-e2e-other"]);
    await delayed.complete();
    expect(await page.evaluate(() => window.staleCrmContent)).toBe(false);
    await expect(page.locator("#crm-detail-title")).toHaveText(current.account.display_name);
    await expect(page.locator("#crm-detail-contacts")).toContainText("Synthetic other CRM contact");
    assertClean();
  } finally {
    delayed.release();
  }
});

test("changing context clears CRM details and rejects a delayed previously authorized response", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openCrm(page);
  await readCrm(page);
  const delayed = await holdCrmResponse(page);
  try {
    await page.locator("#crm-detail-refresh").click();
    await delayed.ready;
    await expectCrmCleared(page);
    // Submit the existing form directly because the native modal makes outside controls inert.
    await page.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "knowledge-worker";
      document.querySelector("#context-form").requestSubmit();
    });
    await waitForWorkspace(page, 7);
    await expect(page.locator("#crm-detail-dialog")).toBeHidden();
    await expect(page.locator("[data-crm-detail]")).toHaveCount(0);
    await watchStaleCrmContent(page);
    await delayed.complete();
    expect(await page.evaluate(() => window.staleCrmContent)).toBe(false);
    await expectCrmCleared(page);
    assertClean();
  } finally {
    delayed.release();
  }
});
