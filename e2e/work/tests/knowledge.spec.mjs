import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  ARTIFACT_DIR,
  BASE_URL,
  BLOCKED_BASE_URL,
  HTTP_UNAVAILABLE_CONSOLE_ERROR,
  monitorPage,
  openView,
} from "./support.mjs";
import {
  KB_HEADERS,
  KB_PATH,
  approveKnowledgeDraft,
  closeKnowledgeEditor,
  createKnowledgeArticle,
  executeKnowledgeDraft,
  newKnowledgeDraft,
  openKnowledge,
  readKnowledgeContent,
} from "./knowledge-support.mjs";

test("Knowledge create and edit bind real PostgreSQL/S3 content, approval, receipt and restore evidence", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const title = `Synthetic Knowledge create ${Date.now()}`;
  const body = "Synthetic internal article. <script>window.kbUnsafe = true</script>";
  const created = await createKnowledgeArticle(page, title, body);
  const initial = await readKnowledgeContent(page, created.article_object_id);
  expect(initial.body).toBe(body);
  expect(initial.article.current_version_object_id).toBe(created.current_version_object_id);
  expect(await page.evaluate(() => window.kbUnsafe)).toBeUndefined();

  await page.locator(`[data-knowledge-edit="${created.article_object_id}"]`).click();
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue(body);
  const editedBody = "Synthetic revised Knowledge content stored in the exact new S3 object version.";
  await page.locator('#knowledge-form textarea[name="content_text"]').fill(editedBody);
  await approveKnowledgeDraft(page);
  const edited = await executeKnowledgeDraft(page);
  expect(edited.previous_version_object_id).toBe(created.current_version_object_id);
  expect(edited.current_version_object_id).not.toBe(created.current_version_object_id);
  expect(edited.source_object_write_receipt_hash).not.toBe(created.source_object_write_receipt_hash);
  const current = await readKnowledgeContent(page, created.article_object_id);
  expect(current.body).toBe(editedBody);
  expect(current.article.current_version_object_id).toBe(edited.current_version_object_id);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, "work-knowledge-complete.png"), fullPage: true });
  assertClean();
});

test("a stale Knowledge edit remains visible and cannot overwrite the newer committed version", async ({ page, context }) => {
  const assertClean = monitorPage(page, {
    baseUrls: [BASE_URL],
    expectedConsoleErrors: ["Failed to load resource: the server responded with a status of 409 (Conflict)"],
  });
  await openKnowledge(page);
  const created = await createKnowledgeArticle(page, `Synthetic conflict ${Date.now()}`, "Original synthetic body");
  await page.locator(`[data-knowledge-edit="${created.article_object_id}"]`).click();
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue("Original synthetic body");
  await page.locator('#knowledge-form textarea[name="content_text"]').fill("Preserved stale draft");

  const other = await context.newPage();
  const assertOtherClean = monitorPage(other, { baseUrls: [BASE_URL] });
  await openKnowledge(other);
  await other.locator(`[data-knowledge-edit="${created.article_object_id}"]`).click();
  await expect(other.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue("Original synthetic body");
  await other.locator('#knowledge-form textarea[name="content_text"]').fill("Newer committed synthetic body");
  await approveKnowledgeDraft(other);
  const newest = await executeKnowledgeDraft(other);

  await page.locator("#knowledge-preview").click();
  await expect(page.locator("#knowledge-form [data-form-message]")).toContainText("Versionskonflikt");
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue("Preserved stale draft");
  await expect(page.locator("#knowledge-execute")).toBeHidden();
  const persisted = await readKnowledgeContent(page, created.article_object_id);
  expect(persisted.body).toBe("Newer committed synthetic body");
  expect(persisted.article.current_version_object_id).toBe(newest.current_version_object_id);
  assertClean();
  assertOtherClean();
  await other.close();
});

test("a real object-store failure rolls back Knowledge metadata and leaves independent Work areas usable", async ({ page }) => {
  const assertClean = monitorPage(page, {
    baseUrls: [BASE_URL],
    expectedConsoleErrors: [HTTP_UNAVAILABLE_CONSOLE_ERROR],
  });
  await openKnowledge(page);
  const title = `Synthetic storage failure ${Date.now()}`;
  const created = await createKnowledgeArticle(page, title, "Last committed synthetic body");
  await page.locator(`[data-knowledge-edit="${created.article_object_id}"]`).click();
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue("Last committed synthetic body");
  await page.locator('#knowledge-form textarea[name="content_text"]').fill("Unsaved synthetic body");
  await approveKnowledgeDraft(page);
  await page.route(`**${KB_PATH}/write-approvals/execute`, (route) => route.continue({
    headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" },
  }));
  await page.locator("#knowledge-confirm").check();
  const failed = page.waitForResponse((response) => new URL(response.url()).pathname === `${KB_PATH}/write-approvals/execute`);
  await page.locator("#knowledge-execute").click();
  expect((await failed).status()).toBe(503);
  await expect(page.locator("#knowledge-form [data-form-message]")).toContainText("Speicherung konnte nicht bestaetigt werden");
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue("Unsaved synthetic body");
  await expect(page.locator("#knowledge-execute")).toBeHidden();
  const persisted = await readKnowledgeContent(page, created.article_object_id);
  expect(persisted.body).toBe("Last committed synthetic body");
  expect(persisted.article.current_version_object_id).toBe(created.current_version_object_id);
  await closeKnowledgeEditor(page);
  for (const [view, selector, text] of [
    ["tasks", "#task-list", "Synthetic E2E task"],
    ["time", "#time-entry-list", "project:synthetic-state"],
    ["tickets", "#ticket-list", "Synthetic E2E ticket"],
    ["crm", "#crm-list", "Synthetic E2E account"],
  ]) {
    await openView(page, view);
    await expect(page.locator(selector)).toContainText(text);
  }
  assertClean();
});

test("disabled Knowledge write feature hides controls and rejects direct preparation", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BLOCKED_BASE_URL] });
  await openKnowledge(page, { baseUrl: BLOCKED_BASE_URL });
  await expect(page.locator("#knowledge-create")).toBeHidden();
  await expect(page.locator("[data-knowledge-edit]")).toHaveCount(0);
  const denied = await page.request.post(`${BLOCKED_BASE_URL}${KB_PATH}/prepare-write`, {
    headers: KB_HEADERS,
    data: { operation: "create", title: "Synthetic blocked", body: "Synthetic blocked content" },
  });
  expect(denied.status()).toBe(403);
  assertClean();
});

test("a non-admin cannot access Knowledge create or edit through UI or direct API", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page, { roleIds: "knowledge-worker" });
  await expect(page.locator("#knowledge-create")).toBeHidden();
  await expect(page.locator("[data-knowledge-edit]")).toHaveCount(0);
  const denied = await page.request.post(`${BASE_URL}${KB_PATH}/prepare-write`, {
    headers: { ...KB_HEADERS, "X-Role-Ids": "knowledge-worker" },
    data: { operation: "create", title: "Synthetic unauthorized", body: "Synthetic unauthorized content" },
  });
  expect(denied.status()).toBe(403);
  assertClean();
});

test("changing an approved Knowledge draft invalidates approval and requires fresh confirmation", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  await newKnowledgeDraft(page, `Synthetic preview reset ${Date.now()}`, "Synthetic initial draft");
  await approveKnowledgeDraft(page);
  await page.locator("#knowledge-confirm").check();
  await page.locator('#knowledge-form textarea[name="content_text"]').fill("Synthetic changed draft");
  await expect(page.locator("#knowledge-preview")).toBeVisible();
  await expect(page.locator("#knowledge-confirm")).not.toBeChecked();
  await expect(page.locator("#knowledge-execute")).toBeHidden();
  await approveKnowledgeDraft(page);
  const saved = await executeKnowledgeDraft(page);
  expect((await readKnowledgeContent(page, saved.article_object_id)).body).toBe("Synthetic changed draft");
  assertClean();
});
