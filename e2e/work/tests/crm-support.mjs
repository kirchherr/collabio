import { expect } from "@playwright/test";

import {
  BASE_URL, TENANT_ID, USER_ID, installContext, installResourceRoutes, openView, resources, waitForWorkspace,
} from "./support.mjs";

export const CRM_MAIN_ID = "crm-account-work-e2e-main";
export const CRM_OTHER_ID = "crm-account-work-e2e-other";
export const CRM_EMPTY_ID = "crm-account-work-e2e-empty";
export const CRM_MAIN_NAME = "Synthetic E2E CRM account <script>window.crmUnsafe=true</script>";
export const CRM_READER_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": "work-reader-e2e", "X-Role-Ids": "knowledge-worker",
};
export const CRM_ADMIN_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": USER_ID, "X-Role-Ids": "tenant-admin",
};

export function crmWorkspacePath(accountId) {
  return `/v1/crm/accounts/${encodeURIComponent(accountId)}/workspace`;
}

export async function openCrm(page) {
  await installContext(page, { userId: "work-reader-e2e", roleIds: "knowledge-worker" });
  await installResourceRoutes(
    page, Object.fromEntries(Object.keys(resources).map((key) => [key, { kind: "ready" }])),
  );
  await page.unroute(`**${resources.crm.path}`);
  await page.goto(`${BASE_URL}/work`);
  await waitForWorkspace(page, 7);
  await openView(page, "crm");
}

export async function readCrm(page, accountId = CRM_MAIN_ID, { refresh = false, status = 200 } = {}) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === crmWorkspacePath(accountId));
  await page.locator(refresh ? "#crm-detail-refresh" : `[data-crm-detail="${accountId}"]`).click();
  const response = await pending;
  expect(response.status()).toBe(status);
  const result = await response.json();
  if (status === 200) {
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.account.object_id).toBe(accountId);
    expect(result.result_contract).toBe("metadata_only_account_workspace");
    expect(result.content_included).toBe(false);
    expect(result.access_checked).toBe(true);
    expect(result.audit_event_id).toBeTruthy();
    await expect(page.locator("#crm-detail-title")).toHaveText(result.account.display_name);
    await expect(page.locator("#crm-detail-content")).toBeVisible();
    await expect(page.getByTestId("crm-detail-contact")).toHaveCount(result.contacts.length);
    await expect(page.getByTestId("crm-detail-activity")).toHaveCount(result.activities.length);
  }
  await expect(page.locator("#crm-detail-refresh")).toBeEnabled();
  return result;
}

export async function expectCrmCleared(page) {
  await expect(page.locator("#crm-detail-content")).toBeHidden();
  for (const section of ["account", "contacts", "activities"]) {
    await expect(page.locator(`#crm-detail-${section}`)).toHaveText("");
  }
}

export async function closeCrm(page) {
  await page.locator("#crm-detail-close").click();
  await expect(page.locator("#crm-detail-dialog")).toBeHidden();
  await expectCrmCleared(page);
}

export async function setCrmAccountReadAcl(page, status) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/authz/object-acl-entries`, {
    headers: { ...CRM_ADMIN_HEADERS, "X-Role-Ids": "security-admin" },
    data: {
      object_id: CRM_MAIN_ID, object_type: "crm.account", acl_subject_type: "user",
      acl_subject_id: "work-reader-e2e", permission: "read", acl_version: 1, status,
      approval_reference: "test-fixture:work-e2e-crm-acl", reason: "Synthetic isolated CRM browser proof only",
    },
  });
  expect(response.status()).toBe(200);
}

export async function crmFeatures(page) {
  const response = await page.request.get(`${BASE_URL}/v1/platform/modules`, { headers: CRM_ADMIN_HEADERS });
  expect(response.status()).toBe(200);
  return (await response.json()).modules.find((module) => module.module_id === "crm_erp").enabled_features;
}

export async function setCrmFeatures(page, features) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/tenant-modules/crm_erp/enable`, {
    headers: CRM_ADMIN_HEADERS,
    data: {
      enabled_features: features, approval_reference: "test-fixture:work-e2e-crm-feature",
      reason: "Synthetic isolated CRM feature denial browser proof only",
    },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).enabled_features).toEqual(features);
}

export async function holdCrmResponse(page, accountId = CRM_MAIN_ID) {
  let release;
  let started;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${crmWorkspacePath(accountId)}`, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    started();
    await gate;
    await route.fulfill({ response });
  }, { times: 1 });
  return {
    ready,
    release,
    async complete() {
      const pending = page.waitForResponse((response) => new URL(response.url()).pathname === crmWorkspacePath(accountId));
      release();
      await (await pending).finished();
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    },
  };
}

export async function watchStaleCrmContent(page) {
  await page.evaluate((staleName) => {
    window.staleCrmContent = false;
    const inspect = () => {
      window.staleCrmContent ||= document.querySelector("#crm-detail-dialog").textContent.includes(staleName);
    };
    new MutationObserver(inspect).observe(document.querySelector("#crm-detail-dialog"), {
      subtree: true, childList: true, characterData: true,
    });
    inspect();
  }, CRM_MAIN_NAME);
}
