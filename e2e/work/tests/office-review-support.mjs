import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_PATH, officeEditor } from "./office-support.mjs";

export const reviewPath = (objectId) => `${OFFICE_PATH}/${encodeURIComponent(objectId)}/review-threads`;
export const threadPath = (objectId, threadId) => `${reviewPath(objectId)}/${encodeURIComponent(threadId)}`;
export const threadCard = (page, threadId) => page.locator(`article[data-thread-id="${threadId}"]`);

export function collectReviewWrites(page) {
  const writes = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.includes("/review-threads")) {
      writes.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
    }
  });
  return writes;
}

export async function openComments(page, objectId) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === reviewPath(objectId));
  await page.locator("#comments-toggle").click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#comments-panel")).toBeVisible();
  await expect(page.locator("#comments-refresh")).toBeEnabled();
  return response.json();
}

export async function openThread(page, objectId, threadId) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === threadPath(objectId, threadId));
  await threadCard(page, threadId).locator('[data-review-action="open"]').click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#comment-thread-detail")).toBeVisible();
  return response.json();
}

export async function prepareComment(page, body, { selection = false } = {}) {
  await page.locator(selection ? "#comment-selection" : "#comment-new").click();
  await expect(page.locator("#comment-composer")).toBeVisible();
  await page.locator("#comment-body").fill(body);
  await page.locator("#comment-prepare").click();
  await expect(page.locator("#comment-confirm-dialog")).toBeVisible();
  await expect(page.locator("#comment-confirm-submit")).toBeDisabled();
}

export async function confirmComment(page, objectId, { threadId = null, status = 200 } = {}) {
  const path = threadId ? `${threadPath(objectId, threadId)}/events` : reviewPath(objectId);
  await page.locator("#comment-confirm-checkbox").check();
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.locator("#comment-confirm-submit").click();
  const response = await pending;
  expect(response.status()).toBe(status);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const result = await response.json();
  await expect(page.locator("#comment-confirm-dialog")).toBeHidden();
  if (status === 200) {
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.object_id).toBe(objectId);
    expect(result.thread.thread_id).toBeTruthy();
    expect(result.event.event_id).toBeTruthy();
    expect(result.applied_revision).toBe(result.event.revision);
    expect(result.rag_indexing_allowed).toBe(false);
    expect(result.search_indexing_allowed).toBe(false);
    expect(result.audit_event_id).toBeTruthy();
    await expect(threadCard(page, result.thread.thread_id)).toBeVisible();
  }
  return result;
}

export async function createReview(page, objectId, body, options = {}) {
  await prepareComment(page, body, options);
  return confirmComment(page, objectId);
}

export async function reviewEvent(page, objectId, threadId, operation, body = null) {
  await threadCard(page, threadId).locator(`[data-review-action="${operation}"]`).click();
  if (operation === "reply") {
    await page.locator("#comment-body").fill(body);
    await page.locator("#comment-prepare").click();
  }
  await expect(page.locator("#comment-confirm-dialog")).toBeVisible();
  await expect(page.locator("#comment-confirm-submit")).toBeDisabled();
  const result = await confirmComment(page, objectId, { threadId });
  await openThread(page, objectId, threadId);
  return result;
}

export async function readReview(page, objectId, threadId, { baseUrl = BASE_URL, headers = OFFICE_HEADERS } = {}) {
  const response = await page.request.get(`${baseUrl}${threadPath(objectId, threadId)}`, { headers });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function selectEditorText(page, text) {
  await officeEditor(page).evaluate((editor, selectedText) => {
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const offset = node.textContent.indexOf(selectedText);
      if (offset === -1) continue;
      editor.focus();
      const range = document.createRange();
      range.setStart(node, offset);
      range.setEnd(node, offset + selectedText.length);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
      return;
    }
    throw new Error("Synthetic selection text was not found in the editor");
  }, text);
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe(text);
  await expect(page.locator("#comment-selection")).toBeEnabled();
}

export async function holdReviewRead(page, objectId, threadId) {
  let release;
  let started;
  let delivered;
  let settled;
  let interrupted = false;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  const delivery = new Promise((resolve) => { delivered = resolve; });
  const network = new Promise((resolve) => { settled = resolve; });
  const matches = (url) => url.pathname === threadPath(objectId, threadId);
  const failed = (request) => { if (matches(new URL(request.url()))) { interrupted = true; settled(); } };
  const responded = (response) => { if (matches(new URL(response.url()))) response.finished().then(settled); };
  page.on("requestfailed", failed);
  page.on("response", responded);
  await page.route(matches, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    started();
    await gate;
    try { await route.fulfill({ response }); }
    catch (error) { if (!interrupted) throw error; }
    finally { delivered(); }
  }, { times: 1 });
  return { ready, release, async complete() {
    release();
    await Promise.all([delivery, network]);
    page.off("requestfailed", failed);
    page.off("response", responded);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  } };
}
