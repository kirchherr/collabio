import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  ARTIFACT_DIR,
  BASE_URL,
  BLOCKED_BASE_URL,
  HTTP_NOT_FOUND_CONSOLE_ERROR,
  HTTP_UNAVAILABLE_CONSOLE_ERROR,
  monitorPage,
  openView,
  waitForWorkspace,
} from "./support.mjs";
import {
  KB_PATH,
  approveKnowledgeDraft,
  closeKnowledgeEditor,
  createKnowledgeArticle,
  executeKnowledgeDraft,
  openKnowledge,
} from "./knowledge-support.mjs";
import {
  READER_HEADERS,
  closeReader,
  contentPath,
  grantReaderAccess,
  holdContentResponse,
  openReaderWorkspace,
  readArticle,
  setReaderAcl,
  watchForStaleReaderContent,
} from "./knowledge-read-support.mjs";

test("a non-admin with write disabled reads literal real S3 content and refreshes an admin's new version", async ({ page, context }) => {
  const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const title = `Synthetic reader <img src=x onerror=window.kbTitleUnsafe=1> ${Date.now()}`;
  const body = "Literal synthetic content.\n<script>window.kbBodyUnsafe = true</script>\n<img src=https://outside.invalid/leak onerror=window.kbBodyUnsafe=true>\n<a href=javascript:alert(1)>Do not activate</a>";
  const created = await createKnowledgeArticle(page, title, body);
  await grantReaderAccess(page, created);

  const reader = await context.newPage();
  const assertReaderClean = monitorPage(reader, { baseUrls: [BLOCKED_BASE_URL] });
  await openReaderWorkspace(reader);
  const initial = await readArticle(reader, created.article_object_id);
  expect(initial.body).toBe(body);
  expect(await reader.locator("#knowledge-reader-body").textContent()).toBe(body);
  expect(initial.article.current_version_object_id).toBe(created.current_version_object_id);
  await expect(reader.locator("#knowledge-reader-dialog script, #knowledge-reader-dialog img, #knowledge-reader-dialog a")).toHaveCount(0);
  expect(await reader.evaluate(() => [window.kbBodyUnsafe, window.kbTitleUnsafe])).toEqual([undefined, undefined]);
  const writeDenied = await reader.request.post(`${BLOCKED_BASE_URL}${KB_PATH}/prepare-write`, {
    headers: READER_HEADERS,
    data: { operation: "create", title: "Synthetic forbidden write", body: "Synthetic reader cannot write" },
  });
  expect(writeDenied.status()).toBe(403);

  await page.locator(`[data-knowledge-edit="${created.article_object_id}"]`).click();
  await expect(page.locator('#knowledge-form textarea[name="content_text"]')).toHaveValue(body);
  const newBody = "Revised synthetic content fetched by the reader from the newly committed S3 version.";
  await page.locator('#knowledge-form textarea[name="content_text"]').fill(newBody);
  await approveKnowledgeDraft(page);
  const edited = await executeKnowledgeDraft(page);
  await closeKnowledgeEditor(page);
  // Migration 0082 propagates the existing reader's article ACL to the new version.
  // Do not grant that version separately: successful refresh proves the transactional copy.
  const updated = await readArticle(reader, created.article_object_id, { refresh: true });
  expect(updated.body).toBe(newBody);
  expect(updated.article.current_version_object_id).toBe(edited.current_version_object_id);
  expect(updated.article.current_version_object_id).not.toBe(initial.article.current_version_object_id);
  await reader.screenshot({ path: path.join(ARTIFACT_DIR, "work-knowledge-reader-complete.png"), fullPage: true });
  assertAuthorClean();
  assertReaderClean();
  await reader.close();
});

test("missing article or current-version ACLs, forged readable IDs and a foreign tenant cannot read source content", async ({ page }) => {
  const assertClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const body = "Synthetic private source must never escape denied reads.";
  const created = await createKnowledgeArticle(page, `Synthetic denied reader ${Date.now()}`, body);
  const read = (articleId, headers = {}) => page.request.get(`${BLOCKED_BASE_URL}${contentPath(articleId)}`, {
    headers: { ...READER_HEADERS, ...headers },
  });
  const missing = await read("kb-article-00000000000000000000000000000000");
  expect(missing.status()).toBe(404);
  const genericMissing = await missing.json();
  const noAcl = await read(created.article_object_id, {
    "X-Readable-Object-Ids": `${created.article_object_id},${created.current_version_object_id}`,
  });
  expect(noAcl.status()).toBe(404);
  expect(await noAcl.json()).toEqual(genericMissing);
  await setReaderAcl(page, created.article_object_id, "kb.article");
  const noVersionAcl = await read(created.article_object_id);
  expect(noVersionAcl.status()).toBe(404);
  expect(await noVersionAcl.json()).toEqual(genericMissing);
  await setReaderAcl(page, created.current_version_object_id, "kb.article_version");
  const authorized = await read(created.article_object_id);
  expect(authorized.status()).toBe(200);
  expect((await authorized.json()).body).toBe(body);
  const foreign = await read(created.article_object_id, { "X-Tenant-Id": "tenant-work-e2e-foreign" });
  expect(foreign.status()).toBe(403);
  expect(await foreign.text()).not.toContain(body);
  expect(await foreign.text()).not.toContain(created.article_object_id);
  assertClean();
});

for (const revokedKind of ["article", "current version"]) {
  test(`revoking the reader's ${revokedKind} ACL clears a previously displayed article on refresh`, async ({ page, context }) => {
    const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
    await openKnowledge(page);
    const body = `Synthetic content revoked at ${revokedKind} boundary.`;
    const created = await createKnowledgeArticle(page, `Synthetic revoked ${revokedKind} ${Date.now()}`, body);
    await grantReaderAccess(page, created);
    const reader = await context.newPage();
    const assertReaderClean = monitorPage(reader, {
      baseUrls: [BLOCKED_BASE_URL], expectedConsoleErrors: [HTTP_NOT_FOUND_CONSOLE_ERROR],
    });
    await openReaderWorkspace(reader);
    await readArticle(reader, created.article_object_id);
    const objectId = revokedKind === "article" ? created.article_object_id : created.current_version_object_id;
    const objectType = revokedKind === "article" ? "kb.article" : "kb.article_version";
    await setReaderAcl(page, objectId, objectType, "revoked");
    const result = await readArticle(reader, created.article_object_id, { refresh: true, status: 404 });
    expect(JSON.stringify(result)).not.toContain(body);
    await expect(reader.locator("#knowledge-reader-message")).toContainText("nicht mehr freigegeben");
    await expect(reader.locator("#knowledge-reader-body")).toHaveText("");
    await expect(reader.locator("#knowledge-reader-version")).toHaveText("");
    await expect(reader.locator("#knowledge-reader-meta")).toBeHidden();
    await expect(reader.locator("#knowledge-reader-refresh")).toHaveText("Erneut laden");
    assertAuthorClean();
    assertReaderClean();
    await reader.close();
  });
}

test("a real S3 read failure clears content safely, permits retry and leaves other Work panels usable", async ({ page, context }) => {
  const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const body = "Synthetic readable content before a request-local object-store outage.";
  const created = await createKnowledgeArticle(page, `Synthetic reader storage ${Date.now()}`, body);
  await grantReaderAccess(page, created);
  const reader = await context.newPage();
  const assertReaderClean = monitorPage(reader, {
    baseUrls: [BLOCKED_BASE_URL], expectedConsoleErrors: [HTTP_UNAVAILABLE_CONSOLE_ERROR],
  });
  await openReaderWorkspace(reader);
  await readArticle(reader, created.article_object_id);
  await reader.route(`**${contentPath(created.article_object_id)}`, (route) => route.continue({
    headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" },
  }), { times: 1 });
  const failed = await readArticle(reader, created.article_object_id, { refresh: true, status: 503 });
  expect(failed).toEqual({ detail: "Knowledge Base storage unavailable" });
  await expect(reader.locator("#knowledge-reader-body")).toHaveText("");
  await expect(reader.locator("#knowledge-reader-meta")).toBeHidden();
  await expect(reader.locator("#knowledge-reader-message")).toHaveText("Der Artikel konnte nicht geladen werden. Bitte versuchen Sie es erneut.");
  await expect(reader.locator("#knowledge-reader-dialog")).not.toContainText("work-e2e-minio");
  expect((await readArticle(reader, created.article_object_id, { refresh: true })).body).toBe(body);
  await closeReader(reader);
  for (const [view, selector, text] of [
    ["tasks", "#task-list", "Synthetic E2E task"],
    ["time", "#time-entry-list", "project:synthetic-state"],
    ["tickets", "#ticket-list", "Synthetic E2E ticket"],
    ["crm", "#crm-list", "Synthetic E2E account"],
  ]) {
    await openView(reader, view);
    await expect(reader.locator(selector)).toContainText(text);
  }
  assertAuthorClean();
  assertReaderClean();
  await reader.close();
});

test("closing a reader discards its delayed real response even after another article opens", async ({ page, context }) => {
  const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const oldBody = "Synthetic delayed article must stay cleared after close.";
  const first = await createKnowledgeArticle(page, `Synthetic delayed first ${Date.now()}`, oldBody);
  await grantReaderAccess(page, first);
  const second = await createKnowledgeArticle(page, `Synthetic delayed second ${Date.now()}`, "Synthetic current article stays displayed.");
  await grantReaderAccess(page, second);
  const reader = await context.newPage();
  const assertReaderClean = monitorPage(reader, { baseUrls: [BLOCKED_BASE_URL] });
  await openReaderWorkspace(reader);
  const delayed = await holdContentResponse(reader, first.article_object_id);
  try {
    await reader.locator(`[data-knowledge-read="${first.article_object_id}"]`).click();
    await delayed.ready;
    await expect(reader.locator("#knowledge-reader-message")).toContainText("wird geladen");
    await closeReader(reader);
    await watchForStaleReaderContent(reader, oldBody);
    const current = await readArticle(reader, second.article_object_id);
    await delayed.complete();
    expect(await reader.evaluate(() => window.staleReaderContent)).toBe(false);
    await expect(reader.locator("#knowledge-reader-body")).toHaveText(current.body);
    await expect(reader.locator("#knowledge-reader-version")).toContainText(second.current_version_object_id);
    assertAuthorClean();
    assertReaderClean();
  } finally {
    delayed.release();
    await reader.close();
  }
});

test("a context change clears a reader and discards its delayed previously authorized response", async ({ page, context }) => {
  const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const oldBody = "Synthetic previous principal's authorized content must not reappear.";
  const created = await createKnowledgeArticle(page, `Synthetic delayed context ${Date.now()}`, oldBody);
  await grantReaderAccess(page, created);
  const reader = await context.newPage();
  const assertReaderClean = monitorPage(reader, { baseUrls: [BLOCKED_BASE_URL] });
  await openReaderWorkspace(reader);
  await readArticle(reader, created.article_object_id);
  const delayed = await holdContentResponse(reader, created.article_object_id);
  try {
    await reader.locator("#knowledge-reader-refresh").click();
    await delayed.ready;
    await expect(reader.locator("#knowledge-reader-body")).toHaveText("");
    // A modal makes outside controls inert, so submit the normal context form directly.
    await reader.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "knowledge-reader";
      document.querySelector("#context-form").requestSubmit();
    });
    await waitForWorkspace(reader, 7);
    await expect(reader.locator("#knowledge-reader-dialog")).toBeHidden();
    await expect(reader.locator("#knowledge-list")).not.toContainText(created.article_object_id);
    await watchForStaleReaderContent(reader, oldBody);
    await delayed.complete();
    expect(await reader.evaluate(() => window.staleReaderContent)).toBe(false);
    await expect(reader.locator("#knowledge-reader-body")).toHaveText("");
    await expect(reader.locator("#knowledge-reader-version")).toHaveText("");
    await expect(reader.locator(`[data-knowledge-read="${created.article_object_id}"]`)).toHaveCount(0);
    assertAuthorClean();
    assertReaderClean();
  } finally {
    delayed.release();
    await reader.close();
  }
});
