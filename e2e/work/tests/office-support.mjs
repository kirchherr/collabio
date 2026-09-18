import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID, installContext } from "./support.mjs";

export const OFFICE_PATH = "/v1/office/documents";
export const OFFICE_EDITOR_ID = "work-office-editor-e2e";
export const OFFICE_READER_ID = "work-reader-e2e";
export const OFFICE_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": OFFICE_EDITOR_ID, "X-Role-Ids": "office-editor",
};
export const OFFICE_READER_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": OFFICE_READER_ID, "X-Role-Ids": "office-reader",
};
export const officeContentPath = (id) => `${OFFICE_PATH}/${encodeURIComponent(id)}/content`;
export const officeEditor = (page) => page.locator("#office-editor .tiptap");
export const textDocument = (text) => ({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] });

export async function openOffice(page, { baseUrl = BASE_URL, userId = OFFICE_EDITOR_ID, roleIds = "office-editor", readableObjectIds = "" } = {}) {
  await installContext(page, { userId, roleIds, readableObjectIds });
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.goto(`${baseUrl}/office`);
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#documents-refresh")).toBeEnabled();
  return response.json();
}

export async function newOfficeDraft(page, title, { text, template = "blank" } = {}) {
  const control = await page.locator("#welcome-new").isVisible() ? "#welcome-new" : "#document-new";
  await page.locator(control).click();
  await page.locator('#new-document-form input[name="title"]').fill(title);
  await page.locator(`#new-document-form input[value="${template}"]`).check();
  await page.locator('#new-document-form button[type="submit"]').click();
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  if (text !== undefined) await officeEditor(page).fill(text);
}

export async function saveOffice(page, { status = 200, objectId = null } = {}) {
  await page.locator("#document-save").click();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-confirm").check();
  const path = objectId ? `${OFFICE_PATH}/${objectId}/versions` : OFFICE_PATH;
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.locator("#save-submit").click();
  const response = await pending;
  expect(response.status()).toBe(status);
  const result = await response.json();
  await expect(page.locator("#save-dialog")).toBeHidden();
  if (status === 200) {
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.document.object_id).toMatch(/^office-doc-[a-f0-9]{32}$/);
    expect(result.version.version_id).toMatch(/^office-version-[a-f0-9]{32}$/);
    expect(result.version.content_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(result.version.source_write_receipt_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(result.rag_indexing_allowed).toBe(false);
    expect(result.search_indexing_allowed).toBe(false);
    expect(result.audit_event_id).toBeTruthy();
    await expect(page.locator("#document-status")).toContainText("Gespeichert");
    await expect(page.locator("#document-version")).toContainText(result.version.version_id);
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  return result;
}

export async function createOfficeDocument(page, title, text) {
  await newOfficeDraft(page, title, { text });
  return saveOffice(page);
}

export async function showDocumentList(page) {
  if (await page.locator("#documents-toggle").isVisible() && await page.locator("#documents-toggle").getAttribute("aria-expanded") !== "true") {
    await page.locator("#documents-toggle").click();
  }
}

export async function openOfficeDocument(page, objectId) {
  await showDocumentList(page);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(objectId));
  await page.locator(`[data-document-id="${objectId}"]`).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  await expect(officeEditor(page)).toBeVisible();
  return response.json();
}

export async function officeContent(page, objectId, { baseUrl = BASE_URL, headers = OFFICE_HEADERS, versionId = null } = {}) {
  const response = await page.request.get(`${baseUrl}${officeContentPath(objectId)}${versionId ? `?version_id=${versionId}` : ""}`, { headers });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function officeVersions(page, objectId) {
  const response = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${objectId}/versions`, { headers: OFFICE_HEADERS });
  expect(response.status()).toBe(200);
  return (await response.json()).versions;
}

export async function setOfficeAcl(page, objectId, { status = "active", creator = false } = {}) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/authz/object-acl-entries`, {
    headers: { ...OFFICE_HEADERS, "X-Role-Ids": "security-admin" },
    data: {
      object_id: objectId, object_type: "office.document", acl_subject_type: "user",
      acl_subject_id: creator ? OFFICE_EDITOR_ID : OFFICE_READER_ID,
      permission: creator ? "admin" : "read", acl_version: 1, status,
      approval_reference: "test-fixture:work-e2e-office-acl", reason: "Synthetic isolated Office browser proof only",
    },
  });
  expect(response.status()).toBe(200);
}

export async function officeFeatures(page) {
  const response = await page.request.get(`${BASE_URL}/v1/platform/modules`, { headers: { ...OFFICE_HEADERS, "X-Role-Ids": "tenant-admin" } });
  expect(response.status()).toBe(200);
  return (await response.json()).modules.find((module) => module.module_id === "office_documents").enabled_features;
}

export async function setOfficeFeatures(page, features) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/tenant-modules/office_documents/enable`, {
    headers: { ...OFFICE_HEADERS, "X-Role-Ids": "tenant-admin" },
    data: { enabled_features: features, approval_reference: "test-fixture:work-e2e-office-feature", reason: "Synthetic Office feature denial proof only" },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).enabled_features).toEqual(features);
}

export async function holdOfficeRead(page, objectId) {
  let release;
  let started;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${officeContentPath(objectId)}`, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    started();
    await gate;
    await route.fulfill({ response });
  }, { times: 1 });
  return { ready, release, async complete() {
    const pending = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(objectId));
    release();
    await (await pending).finished();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  } };
}

export async function observeStaleOfficeContent(page, text) {
  await page.evaluate((staleText) => {
    window.staleOfficeContent = false;
    new MutationObserver(() => {
      window.staleOfficeContent ||= document.querySelector("#office-editor").textContent.includes(staleText);
    }).observe(document.querySelector("#office-editor"), { subtree: true, childList: true, characterData: true });
  }, text);
}
