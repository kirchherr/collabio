import { expect } from "@playwright/test";

import {
  BASE_URL,
  TENANT_ID,
  USER_ID,
  installContext,
  installResourceRoutes,
  openView,
  resources,
  waitForWorkspace,
} from "./support.mjs";

export const KB_PATH = "/v1/admin/kb/articles";
export const KB_HEADERS = {
  "X-Tenant-Id": TENANT_ID,
  "X-User-Id": USER_ID,
  "X-Role-Ids": "tenant-admin",
};

export async function openKnowledge(page, { baseUrl = BASE_URL, roleIds = "tenant-admin", userId = USER_ID } = {}) {
  await installContext(page, { roleIds, userId });
  // Keep the independent source-state fixtures; every Knowledge Base request uses the real API.
  await installResourceRoutes(
    page,
    Object.fromEntries(Object.keys(resources).map((key) => [key, { kind: "ready" }])),
  );
  await page.unroute(`**${resources.knowledge.path}`);
  await page.goto(`${baseUrl}/work`);
  await waitForWorkspace(page, 7);
  await openView(page, "knowledge");
}

export async function newKnowledgeDraft(page, title, body) {
  await page.locator("#knowledge-create").click();
  await page.locator('#knowledge-form input[name="title"]').fill(title);
  await page.locator('#knowledge-form textarea[name="content_text"]').fill(body);
}

export async function approveKnowledgeDraft(page) {
  await page.locator("#knowledge-preview").click();
  await expect(page.locator("#knowledge-approve")).toBeEnabled();
  await page.locator("#knowledge-approve").click();
  await expect(page.locator("#knowledge-confirm")).toBeVisible();
  await expect(page.locator("#knowledge-confirm")).toBeEnabled();
  await expect(page.locator("#knowledge-execute")).toBeDisabled();
}

export async function executeKnowledgeDraft(page) {
  await page.locator("#knowledge-confirm").check();
  const completed = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `${KB_PATH}/write-approvals/execute`,
  );
  await page.locator("#knowledge-execute").click();
  const response = await completed;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.write_unit_of_work_transaction_scope).toBe("shared_postgres_metadata_transaction");
  for (const key of [
    "write_unit_of_work_committed",
    "source_object_persisted",
    "source_object_write_receipt_persisted",
    "article_metadata_persisted",
    "article_version_metadata_persisted",
    "source_version_evidence_refreshed",
    "restore_evidence_refreshed",
  ]) {
    expect(result[key], key).toBe(true);
  }
  expect(result.rag_indexing_allowed).toBe(false);
  expect(result.search_indexing_allowed).toBe(false);
  expect(result.source_content_recovery_required).toBe(false);
  for (const key of [
    "source_object_write_receipt_hash",
    "source_content_recovery_evidence_hash",
    "production_write_deployment_gate_evidence_hash",
    "refreshed_source_version_evidence_hash",
    "refreshed_restore_evidence_hash",
    "approved_write_approval_evidence_hash",
    "transition_source_evidence_hash",
  ]) {
    expect(result[key], key).toMatch(/^sha256:[a-f0-9]{64}$/);
  }
  await expect(page.locator("#knowledge-result")).toContainText("Artikel gespeichert");
  await expect(page.locator('#knowledge-dialog [data-close-dialog]').first()).toBeEnabled();
  return result;
}

export async function closeKnowledgeEditor(page) {
  await page.locator('#knowledge-dialog [data-close-dialog]').first().click();
  await expect(page.locator("#knowledge-dialog")).toBeHidden();
}

export async function readKnowledgeContent(page, articleId, baseUrl = BASE_URL) {
  const response = await page.request.get(`${baseUrl}${KB_PATH}/${articleId}/edit-content`, {
    headers: KB_HEADERS,
  });
  expect(response.status()).toBe(200);
  return response.json();
}

export async function createKnowledgeArticle(page, title, body) {
  await newKnowledgeDraft(page, title, body);
  await approveKnowledgeDraft(page);
  const result = await executeKnowledgeDraft(page);
  await closeKnowledgeEditor(page);
  return result;
}
