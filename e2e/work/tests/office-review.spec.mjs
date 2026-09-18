import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_HEADERS, OFFICE_PATH, OFFICE_READER_HEADERS, OFFICE_READER_ID,
  createOfficeDocument, newOfficeDraft, officeContent, officeEditor, officeFeatures,
  officeVersions, openOffice, openOfficeDocument, saveOffice, setOfficeAcl, setOfficeFeatures,
} from "./office-support.mjs";
import {
  collectReviewWrites, confirmComment, createReview, holdReviewRead, openComments, openThread,
  prepareComment, readReview, reviewEvent, reviewPath, selectEditorText, threadCard, threadPath,
} from "./office-review-support.mjs";

const featureTest = test.extend({
  restoreOfficeFeatures: [async ({ request }, use) => {
    let previous = null;
    try { await use((features) => { previous = { ...features }; }); }
    finally { if (previous !== null) await setOfficeFeatures({ request }, previous); }
  }, { timeout: 20_000 }],
});

async function apiReply(page, objectId, threadId, revision, body) {
  const response = await page.request.post(`${BASE_URL}${threadPath(objectId, threadId)}/events`, {
    headers: OFFICE_HEADERS,
    data: { operation: "reply", expected_revision: revision, body, mutation_reference: `synthetic-review-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

async function refreshComments(page, objectId, status = 200) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === reviewPath(objectId));
  await page.locator("#comments-refresh").click();
  const response = await pending;
  expect(response.status()).toBe(status);
  await response.json();
}

async function observeLateReview(page, text) {
  await page.evaluate((protectedText) => {
    window.staleOfficeReview = false;
    new MutationObserver(() => {
      window.staleOfficeReview ||= document.querySelector("#comments-panel").textContent.includes(protectedText);
    }).observe(document.querySelector("#comments-panel"), { subtree: true, childList: true, characterData: true });
  }, text);
}

test("Office review binds a Unicode selection, confirms every event and persists a complete discussion", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic review recovery discussion", "Before 😀 Café e\u0301 after");
  const objectId = saved.document.object_id;
  const writes = collectReviewWrites(page);
  await openComments(page, objectId);
  await selectEditorText(page, "😀 Café e\u0301");
  const body = '<img src="https://review.invalid/leak" onerror="window.reviewExecuted=true"> Review 😀';
  await prepareComment(page, body, { selection: true });
  await expect(page.locator("#comment-anchor")).toContainText("😀 Café e\u0301");
  expect(writes).toHaveLength(0);
  await page.locator("#comment-confirm-cancel").click();
  await expect(page.locator("#comment-body")).toHaveValue(body);
  expect(writes).toHaveLength(0);
  await page.locator("#comment-prepare").click();
  const created = await confirmComment(page, objectId);
  expect(created.quote).toBe("😀 Café e\u0301");
  expect(created.thread.anchor_version_id).toBe(saved.version.version_id);
  expect(created.thread.anchor).toEqual({ from: 8, to: 8 + "😀 Café e\u0301".length });
  expect(created.event.operation).toBe("create");
  const threadId = created.thread.thread_id;
  await openThread(page, objectId, threadId);
  await expect(page.locator("#comment-thread-quote")).toHaveText("😀 Café e\u0301");
  await expect(page.locator("#comment-events")).toContainText(body);
  await expect(page.locator("#comment-events img, #comment-events script")).toHaveCount(0);
  expect(await page.evaluate(() => window.reviewExecuted)).toBeUndefined();
  await reviewEvent(page, objectId, threadId, "reply", "Verified synthetic reply");
  await reviewEvent(page, objectId, threadId, "resolve");
  const reopened = await reviewEvent(page, objectId, threadId, "reopen");
  expect(reopened.thread.status).toBe("open");
  expect(reopened.thread.revision).toBe(4);
  expect(writes).toHaveLength(4);
  expect(writes.every((entry) => entry.body.human_confirmation === true)).toBe(true);
  expect(new Set(writes.map((entry) => entry.body.mutation_reference)).size).toBe(4);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  expect((await officeContent(page, objectId)).content).toEqual(saved.content);
  await openOffice(page);
  await openOfficeDocument(page, objectId);
  await openComments(page, objectId);
  const persisted = await openThread(page, objectId, threadId);
  expect(persisted.events.map((event) => event.operation)).toEqual(["create", "reply", "resolve", "reopen"]);
  expect(persisted.events.map((event) => event.revision)).toEqual([1, 2, 3, 4]);
  expect(persisted.quote).toBe(created.quote);
  await expect(page.locator("#document-save")).toBeDisabled();
  verifyBrowser();
});

test("Office historical review stays on its exact saved anchor while current rights allow existing discussion", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic historical review", "Original anchored wording");
  const objectId = first.document.object_id;
  await openComments(page, objectId);
  const created = await createReview(page, objectId, "Review of the first saved version");
  await page.locator("#comments-close").click();
  await officeEditor(page).fill("Changed current wording");
  const second = await saveOffice(page, { objectId });
  const current = await openComments(page, objectId);
  expect(current.threads).toEqual([]);
  await expect(page.locator(`[data-thread-id="${created.thread.thread_id}"]`)).toHaveCount(0);
  await page.locator("#history-tab").click();
  await expect(page.locator(`[data-version-id="${first.version.version_id}"]`)).toBeVisible();
  const historical = page.waitForResponse((response) => new URL(response.url()).searchParams.get("version_id") === first.version.version_id);
  await page.locator(`[data-version-id="${first.version.version_id}"]`).click();
  expect((await historical).status()).toBe(200);
  await openComments(page, objectId);
  await expect(page.locator("#comment-new")).toBeDisabled();
  await expect(page.locator("#comment-selection")).toBeDisabled();
  const detail = await openThread(page, objectId, created.thread.thread_id);
  expect(detail.thread.anchor_version_id).toBe(first.version.version_id);
  expect(detail.current_version_id).toBe(second.version.version_id);
  expect(detail.can_comment).toBe(true);
  await reviewEvent(page, objectId, created.thread.thread_id, "reply", "Reply still belongs to the original saved version");
  expect((await readReview(page, objectId, created.thread.thread_id)).thread.anchor_version_id).toBe(first.version.version_id);
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  expect((await officeContent(page, objectId)).version.version_id).toBe(second.version.version_id);
  await expect(officeEditor(page)).toHaveText("Original anchored wording");
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
});

test("Office review ordinary readers can read but forged, foreign and revoked access cannot expose discussions", async ({ page }) => {
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic reader review", "Authorized source");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  const created = await createReview(page, objectId, "Protected review body");
  const threadId = created.thread.thread_id;
  await setOfficeAcl(page, objectId);
  await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(page, objectId);
  await openComments(page, objectId);
  const read = await openThread(page, objectId, threadId);
  expect(read.can_comment).toBe(false);
  expect(read.can_resolve).toBe(false);
  await expect(page.locator("#comment-new")).toBeDisabled();
  for (const action of ["reply", "resolve"]) await expect(threadCard(page, threadId).locator(`[data-review-action="${action}"]`)).toBeDisabled();
  const deniedWrite = await page.request.post(`${BASE_URL}${threadPath(objectId, threadId)}/events`, {
    headers: OFFICE_READER_HEADERS,
    data: { operation: "reply", expected_revision: 1, body: "Must not persist", mutation_reference: `synthetic-review-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(deniedWrite.status()).toBe(403);
  for (const headers of [
    { ...OFFICE_HEADERS, "X-User-Id": "work-assignee-e2e", "X-Readable-Object-Ids": `${objectId},${threadId}` },
    { ...OFFICE_HEADERS, "X-Tenant-Id": "tenant-work-e2e-foreign", "X-Readable-Object-Ids": `${objectId},${threadId}` },
  ]) {
    const denied = await page.request.get(`${BASE_URL}${threadPath(objectId, threadId)}`, { headers });
    expect([403, 404, 423]).toContain(denied.status());
    expect(await denied.text()).not.toContain("Protected review body");
  }
  await setOfficeAcl(page, objectId, { status: "revoked" });
  await refreshComments(page, objectId, 404);
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#comments-list")).toHaveText("");
  await expect(page.locator("#office-editor")).toHaveText("");
  expect((await readReview(page, objectId, threadId)).events).toHaveLength(1);
});

test("Office stale review revision conflicts preserve the reply and require fresh thread state", async ({ page }) => {
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic review conflict", "Review concurrency");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  const created = await createReview(page, objectId, "First comment");
  const threadId = created.thread.thread_id;
  await openThread(page, objectId, threadId);
  await threadCard(page, threadId).locator('[data-review-action="reply"]').click();
  await page.locator("#comment-body").fill("Preserved local reply");
  await page.locator("#comment-prepare").click();
  await apiReply(page, objectId, threadId, 1, "Concurrent saved reply");
  await confirmComment(page, objectId, { threadId, status: 409 });
  await expect(page.locator("#comment-body")).toHaveValue("Preserved local reply");
  await expect(page.locator("#comments-status")).toContainText("hat sich geändert");
  expect((await readReview(page, objectId, threadId)).events.map((event) => event.body)).toEqual(["First comment", "Concurrent saved reply"]);
  await refreshComments(page, objectId);
  await openThread(page, objectId, threadId);
  await expect(page.locator("#comment-body")).toHaveValue("Preserved local reply");
  await page.locator("#comment-prepare").click();
  const retried = await confirmComment(page, objectId, { threadId });
  expect(retried.event.revision).toBe(3);
  expect((await readReview(page, objectId, threadId)).events.filter((event) => event.body === "Preserved local reply")).toHaveLength(1);
});

test("Office uncertain review storage writes retry the identical command and failed reads clear protected bodies", async ({ page }) => {
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic review storage retry", "Storage proof");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  const writes = collectReviewWrites(page);
  await page.route((url) => url.pathname === reviewPath(objectId), async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.continue({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" } });
  }, { times: 1 });
  await prepareComment(page, "Retriable stored comment");
  await confirmComment(page, objectId, { status: 503 });
  await expect(page.locator("#comment-body")).toHaveValue("Retriable stored comment");
  await expect(page.locator("#comment-prepare")).toContainText("Speicherung prüfen");
  await page.locator("#comment-prepare").click();
  const retried = await confirmComment(page, objectId);
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
  const threadId = retried.thread.thread_id;
  expect((await readReview(page, objectId, threadId)).events).toHaveLength(1);
  await openThread(page, objectId, threadId);
  await page.route((url) => url.pathname === threadPath(objectId, threadId), async (route) => {
    await route.continue({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" } });
  }, { times: 1 });
  const failed = page.waitForResponse((response) => new URL(response.url()).pathname === threadPath(objectId, threadId) && response.status() === 503);
  await threadCard(page, threadId).locator('[data-review-action="open"]').click();
  expect((await failed).headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#comments-panel")).not.toContainText("Retriable stored comment");
  await openThread(page, objectId, threadId);
  await expect(page.locator("#comment-events")).toContainText("Retriable stored comment");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});

test("Office closing review suppresses a late real thread response", async ({ page }) => {
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic close review race", "Stable document");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  const created = await createReview(page, objectId, "Late protected review body");
  await refreshComments(page, objectId);
  await observeLateReview(page, "Late protected review body");
  const held = await holdReviewRead(page, objectId, created.thread.thread_id);
  try {
    await threadCard(page, created.thread.thread_id).locator('[data-review-action="open"]').click();
    await held.ready;
    await page.locator("#comments-close").click();
    await held.complete();
    await expect(page.locator("#comments-panel")).toBeHidden();
    await expect(page.locator("#comments-panel")).not.toContainText("Late protected review body");
    expect(await page.evaluate(() => window.staleOfficeReview)).toBe(false);
    await expect(officeEditor(page)).toHaveText("Stable document");
  } finally { held.release(); }
});

test("Office context changes discard pending reviews and unconfirmed commands", async ({ page }) => {
  await openOffice(page);
  const saved = await createOfficeDocument(page, "Synthetic context review race", "Previous context source");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  const created = await createReview(page, objectId, "Previous context review secret");
  const writes = collectReviewWrites(page);
  await prepareComment(page, "Unconfirmed review must not persist");
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.evaluate((objectId) => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#readable-object-ids").value = objectId;
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }, objectId);
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#comment-confirm-dialog")).toBeHidden();
  await expect(page.locator("#document-workspace")).toBeHidden();
  expect(writes).toHaveLength(0);
  await openOffice(page);
  await openOfficeDocument(page, objectId);
  await openComments(page, objectId);
  await observeLateReview(page, "Previous context review secret");
  const held = await holdReviewRead(page, objectId, created.thread.thread_id);
  try {
    await threadCard(page, created.thread.thread_id).locator('[data-review-action="open"]').click();
    await held.ready;
    const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    await page.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect((await pending).status()).toBe(200);
    await held.complete();
    await expect(page.locator("#comments-list")).toHaveText("");
    await expect(page.locator("#office-editor")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficeReview)).toBe(false);
    expect(writes).toHaveLength(0);
  } finally { held.release(); }
});

featureTest("Office review requires a clean saved version and fresh enabled write feature at confirmation", async ({ page, restoreOfficeFeatures }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic gated review", { text: "Unsaved review source" });
  await expect(page.locator("#comments-toggle")).toBeDisabled();
  await expect(page.locator("#comment-new")).toBeDisabled();
  await expect(page.locator("#comment-selection")).toBeDisabled();
  const saved = await saveOffice(page);
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  await officeEditor(page).fill("Dirty source has no saved anchor");
  await expect(page.locator("#comment-new")).toBeDisabled();
  await expect(page.locator("#comment-selection")).toBeDisabled();
  await officeEditor(page).press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator("#comment-new")).toBeEnabled();
  await prepareComment(page, "Feature removed before confirmed write");
  const previous = await officeFeatures(page);
  restoreOfficeFeatures(previous);
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  await confirmComment(page, objectId, { status: 403 });
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#comments-list")).toHaveText("");
  await expect(page.locator("#comment-body")).toHaveValue("");
  const response = await page.request.get(`${BASE_URL}${reviewPath(objectId)}`, { headers: OFFICE_HEADERS });
  expect(response.status()).toBe(200);
  expect((await response.json()).threads).toEqual([]);
});
