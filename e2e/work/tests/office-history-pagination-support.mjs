import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID } from "./support.mjs";
import { OFFICE_PATH, officeContent, openOffice, openOfficeDocument } from "./office-support.mjs";

export const HISTORY_EDITOR_ID = "work-history-editor-e2e";
export const HISTORY_READER_ID = "work-history-reader-e2e";
export const HISTORY_HEADERS = { "X-Tenant-Id": TENANT_ID, "X-User-Id": HISTORY_EDITOR_ID, "X-Role-Ids": "office-editor" };
export const HISTORY_READER_HEADERS = { "X-Tenant-Id": TENANT_ID, "X-User-Id": HISTORY_READER_ID, "X-Role-Ids": "office-reader" };
export const historyPath = (objectId) => `${OFFICE_PATH}/${objectId}/versions`;
export const historyRows = (page) => page.locator("#document-history [data-version-id]");
export const matchesHistoryPage = (response, objectId, cursor = null) => {
  const url = new URL(response.url());
  return response.request().method() === "GET" && url.pathname === historyPath(objectId) &&
    url.searchParams.get("page_size") === "50" && url.searchParams.get("cursor") === cursor;
};

export async function historyResponse(response, objectId) {
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const result = await response.json();
  expect(result.tenant_id).toBe(TENANT_ID);
  expect(result.object_id).toBe(objectId);
  expect(result.page_size).toBe(50);
  expect(result.versions.length).toBeGreaterThan(0);
  expect(result.versions.length).toBeLessThanOrEqual(50);
  expect(result.has_more).toBe(result.next_cursor !== null);
  expect(result.history_head_version_id).toMatch(/^office-version-/);
  expect(result.current_version_id).toMatch(/^office-version-/);
  for (let index = 1; index < result.versions.length; index += 1) {
    expect(result.versions[index - 1].previous_version_id).toBe(result.versions[index].version_id);
  }
  return result;
}

export async function historyPage(page, objectId, { cursor = null, headers = HISTORY_HEADERS, baseUrl = BASE_URL } = {}) {
  const params = new URLSearchParams({ page_size: "50" });
  if (cursor) params.set("cursor", cursor);
  return historyResponse(await page.request.get(`${baseUrl}${historyPath(objectId)}?${params}`, { headers }), objectId);
}

export async function allHistory(page, objectId, options = {}) {
  let result = await historyPage(page, objectId, options);
  const first = result;
  const versions = [...result.versions];
  while (result.has_more) {
    expect(versions.length).toBeLessThan(1000);
    result = await historyPage(page, objectId, { ...options, cursor: result.next_cursor });
    expect(result.history_head_version_id).toBe(first.history_head_version_id);
    expect(versions.at(-1).previous_version_id).toBe(result.versions[0].version_id);
    versions.push(...result.versions);
  }
  expect(versions.at(-1).previous_version_id).toBeNull();
  expect(new Set(versions.map((version) => version.version_id)).size).toBe(versions.length);
  return { first, versions };
}

export async function openHistoryPanel(page, objectId) {
  if (!await page.locator("#history-tab").isVisible()) await page.locator("#inspector-toggle").click();
  const pending = page.waitForResponse((response) => matchesHistoryPage(response, objectId));
  await page.locator("#history-tab").click();
  const result = await historyResponse(await pending, objectId);
  await expect(page.locator("#history-refresh")).toBeEnabled();
  await expect(historyRows(page)).toHaveCount(result.versions.length);
  return result;
}

export async function openHistoryFixture(page, options = {}) {
  const list = await openOffice(page, { userId: HISTORY_EDITOR_ID, roleIds: "office-editor", ...options });
  expect(list.documents).toHaveLength(1);
  const objectId = list.documents[0].object_id;
  const saved = await openOfficeDocument(page, objectId);
  const first = await openHistoryPanel(page, objectId);
  expect(first.history_head_version_id).toBe(saved.document.current_version_id);
  return { objectId, saved, first };
}

export async function openHistoryComparison(page, objectId) {
  const pending = page.waitForResponse((response) => matchesHistoryPage(response, objectId));
  await page.locator("#history-compare").click();
  const result = await historyResponse(await pending, objectId);
  await expect(page.locator("#compare-dialog")).toBeVisible();
  await expect(page.locator("#compare-load")).toBeEnabled();
  return result;
}

export async function appendHistory(page, objectId, previous, { comparison = false } = {}) {
  expect(previous.has_more).toBe(true);
  const pending = page.waitForResponse((response) => matchesHistoryPage(response, objectId, previous.next_cursor));
  await page.locator(comparison ? "#compare-history-more" : "#history-more").click();
  const result = await historyResponse(await pending, objectId);
  expect(result.history_head_version_id).toBe(previous.history_head_version_id);
  expect(previous.versions.at(-1).previous_version_id).toBe(result.versions[0].version_id);
  await expect(page.locator(comparison ? "#compare-history-refresh" : "#history-refresh")).toBeEnabled();
  return result;
}

export async function appendAllHistory(page, objectId, first, options = {}) {
  let result = first;
  const versions = [...first.versions];
  while (result.has_more) {
    expect(versions.length).toBeLessThan(1000);
    result = await appendHistory(page, objectId, result, options);
    versions.push(...result.versions);
  }
  expect(versions.length).toBeGreaterThanOrEqual(225);
  expect(versions.at(-1).previous_version_id).toBeNull();
  expect(new Set(versions.map((version) => version.version_id)).size).toBe(versions.length);
  return versions;
}

export async function saveHistoryVersion(page, source, text, label) {
  const response = await page.request.post(`${BASE_URL}${historyPath(source.document.object_id)}`, {
    headers: HISTORY_HEADERS,
    data: { title: label, document: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] },
      expected_current_version_id: source.version.version_id,
      mutation_reference: `history-pagination-${Date.now()}-${source.version.version_id}`, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const saved = await response.json();
  expect(saved.version.previous_version_id).toBe(source.version.version_id);
  return saved;
}

export async function prepareHistoryHead(page, text, label) {
  const listResponse = await page.request.get(`${BASE_URL}${OFFICE_PATH}`, { headers: HISTORY_HEADERS });
  expect(listResponse.status()).toBe(200);
  const list = await listResponse.json();
  expect(list.documents).toHaveLength(1);
  const current = await officeContent(page, list.documents[0].object_id, { headers: HISTORY_HEADERS });
  return saveHistoryVersion(page, current, text, label);
}

export async function holdHistoryPage(page, objectId, cursor) {
  let release;
  let started;
  let failStarted;
  let job;
  let request;
  const failures = new Map();
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve, reject) => { started = resolve; failStarted = reject; });
  const matches = (url) => url.pathname === historyPath(objectId) && url.searchParams.get("cursor") === cursor;
  const failed = (value) => { if (matches(new URL(value.url()))) failures.set(value, value.failure()?.errorText); };
  page.on("requestfailed", failed);
  const handler = (route) => {
    job = (async () => {
      request = route.request();
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      const body = await response.body();
      expect(response.status()).toBe(200);
      expect(JSON.parse(body.toString("utf8")).object_id).toBe(objectId);
      started();
      await gate;
      try { await route.fulfill({ response, body }); }
      catch (error) {
        if (!String(error).includes("Route is already handled!")) throw error;
        expect(failures.get(request)).toBe("net::ERR_ABORTED");
      }
    })().catch((error) => { failStarted(error); throw error; });
    return job;
  };
  await page.route(matches, handler, { times: 1 });
  return { ready, async finishCancelled() {
    try {
      await expect.poll(() => failures.get(request)).toBe("net::ERR_ABORTED");
      release();
      await job;
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    } finally { release(); await page.unroute(matches, handler); page.off("requestfailed", failed); }
  }, async dispose() {
    release();
    try { if (job) await job; }
    finally { await page.unroute(matches, handler); page.off("requestfailed", failed); }
  } };
}
