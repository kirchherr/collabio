import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_PATH, captureOfficeResponse, officeEditor } from "./office-support.mjs";

export const suggestionsPath = (objectId) => `${OFFICE_PATH}/${encodeURIComponent(objectId)}/suggestions`;
export const suggestionPath = (objectId, suggestionId) => `${suggestionsPath(objectId)}/${encodeURIComponent(suggestionId)}`;
export const suggestionCard = (page, suggestionId) => page.locator(`article[data-suggestion-id="${suggestionId}"]`);

export function collectSuggestionWrites(page) {
  const writes = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path.includes("/suggestions")) writes.push({ path, body: request.postDataJSON() });
  });
  return writes;
}

export async function openSuggestions(page, objectId) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === suggestionsPath(objectId) && response.request().method() === "GET")
    .then(async (response) => ({ response, result: await response.json() }));
  await page.locator("#suggestions-toggle").click();
  const { response, result } = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#suggestions-panel")).toBeVisible();
  await expect(page.locator("#suggestions-refresh")).toBeEnabled();
  return result;
}

export async function openSuggestion(page, objectId, suggestionId) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === suggestionPath(objectId, suggestionId))
    .then(async (response) => ({ response, result: await response.json() }));
  await suggestionCard(page, suggestionId).locator('[data-suggestion-action="open"]').click();
  const { response, result } = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#suggestion-detail")).toBeVisible();
  await expect(page.locator("#suggestions-refresh")).toBeEnabled();
  return result;
}

export async function prepareSuggestion(page, selectedText, replacement) {
  await selectSuggestionText(page, selectedText);
  await expect(page.locator("#suggestion-new")).toBeEnabled();
  await page.locator("#suggestion-new").click();
  await expect(page.locator("#suggestion-composer")).toBeVisible();
  await expect(page.locator("#suggestion-before")).toHaveText(selectedText);
  await page.locator("#suggestion-replacement").fill(replacement);
  await page.locator("#suggestion-prepare").click();
  await expect(page.locator("#suggestion-confirm-dialog")).toBeVisible();
  await expect(page.locator("#suggestion-confirm-submit")).toBeDisabled();
}

export async function prepareSuggestionDecision(page, suggestionId, operation) {
  await suggestionCard(page, suggestionId).locator(`[data-suggestion-action="${operation}"]`).click();
  await expect(page.locator("#suggestion-confirm-dialog")).toBeVisible();
  await expect(page.locator("#suggestion-confirm-submit")).toBeDisabled();
}

export async function confirmSuggestion(page, objectId, { suggestionId = null, status = 200, extraHeaders = {} } = {}) {
  const path = suggestionId ? `${suggestionPath(objectId, suggestionId)}/decisions` : suggestionsPath(objectId);
  const captured = await captureOfficeResponse(page, (url) => url.pathname === path, { method: "POST", extraHeaders });
  await page.locator("#suggestion-confirm-checkbox").check();
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.locator("#suggestion-confirm-submit").click();
  const response = await pending;
  const upstream = await captured.received;
  expect(response.status()).toBe(status);
  expect(upstream.status).toBe(status);
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect(upstream.headers["cache-control"]).toContain("no-store");
  await expect(page.locator("#suggestion-confirm-dialog")).toBeHidden();
  const result = upstream.json;
  if (status === 200) {
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.object_id).toBe(objectId);
    expect(result.suggestion.suggestion_id).toBeTruthy();
    expect(result.applied_revision).toBe(result.suggestion.revision);
    expect(result.rag_indexing_allowed).toBe(false);
    expect(result.search_indexing_allowed).toBe(false);
    expect(result.audit_event_id).toBeTruthy();
    await expect(page.locator("#suggestions-refresh")).toBeEnabled();
  } else {
    const details = {
      400: "Document validation failed", 403: "Document write is not allowed",
      404: "Document not found", 409: "The document has a newer or conflicting saved version",
      503: "Office storage unavailable",
    };
    // Feature dependencies may use their existing generic denial detail.
    if (status !== 403) expect(result.detail).toBe(details[status]);
  }
  return result;
}

export async function createSuggestion(page, objectId, selectedText, replacement) {
  await prepareSuggestion(page, selectedText, replacement);
  return confirmSuggestion(page, objectId);
}

export async function refreshSuggestions(page, objectId, status = 200) {
  const captured = await captureOfficeResponse(page, (url) => url.pathname === suggestionsPath(objectId));
  await page.locator("#suggestions-refresh").click();
  const response = await captured.received;
  expect(response.status).toBe(status);
  expect(response.headers["cache-control"]).toContain("no-store");
  if (status === 200) await expect(page.locator("#suggestions-refresh")).toBeEnabled();
  return response.json;
}

export async function readSuggestion(page, objectId, suggestionId, { baseUrl = BASE_URL, headers = OFFICE_HEADERS } = {}) {
  const response = await page.request.get(`${baseUrl}${suggestionPath(objectId, suggestionId)}`, { headers });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function readSuggestions(page, objectId, { versionId = null } = {}) {
  const response = await page.request.get(`${BASE_URL}${suggestionsPath(objectId)}${versionId ? `?anchor_version_id=${versionId}` : ""}`, { headers: OFFICE_HEADERS });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function selectSuggestionText(page, text) {
  await officeEditor(page).evaluate((editor, selectedText) => {
    for (const block of editor.querySelectorAll("p,h1,h2,h3")) {
      const offset = block.textContent.indexOf(selectedText);
      if (offset < 0) continue;
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
      let node;
      let position = 0;
      let start = null;
      let end = null;
      while ((node = walker.nextNode())) {
        const next = position + node.textContent.length;
        if (!start && offset >= position && offset < next) start = { node, offset: offset - position };
        if (offset + selectedText.length > position && offset + selectedText.length <= next) {
          end = { node, offset: offset + selectedText.length - position };
          break;
        }
        position = next;
      }
      if (!start || !end) throw new Error("Synthetic selection boundaries are missing");
      editor.focus();
      const range = document.createRange();
      range.setStart(start.node, start.offset);
      range.setEnd(end.node, end.offset);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
      return;
    }
    throw new Error("Synthetic proposal text was not found in the editor");
  }, text);
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe(text);
}

export async function holdSuggestionRead(page, objectId, suggestionId) {
  let release;
  let started;
  let delivered;
  let settled;
  let interrupted = false;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  const delivery = new Promise((resolve) => { delivered = resolve; });
  const network = new Promise((resolve) => { settled = resolve; });
  const matches = (url) => url.pathname === suggestionPath(objectId, suggestionId);
  const failed = (request) => { if (matches(new URL(request.url()))) { interrupted = true; settled(); } };
  const responded = (response) => { if (matches(new URL(response.url()))) response.finished().then(settled); };
  page.on("requestfailed", failed);
  page.on("response", responded);
  await page.route(matches, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
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

export async function observeStaleSuggestion(page, text) {
  await page.evaluate((protectedText) => {
    window.staleOfficeSuggestion = false;
    new MutationObserver(() => {
      window.staleOfficeSuggestion ||= document.querySelector("#suggestions-panel").textContent.includes(protectedText);
    }).observe(document.querySelector("#suggestions-panel"), { subtree: true, childList: true, characterData: true });
  }, text);
}
