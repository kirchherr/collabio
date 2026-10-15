import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID } from "./support.mjs";
import { OFFICE_PATH, openOffice, showDocumentList } from "./office-support.mjs";

export const DISCOVERY_EDITOR_ID = "work-discovery-editor-e2e";
export const DISCOVERY_READER_ID = "work-discovery-reader-e2e";
export const DISCOVERY_COUNT = 225;
export const DISCOVERY_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": DISCOVERY_EDITOR_ID, "X-Role-Ids": "office-editor",
};
export const DISCOVERY_READER_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": DISCOVERY_READER_ID, "X-Role-Ids": "office-reader",
};
export const discoveryCards = (page) => page.locator("#documents-list [data-document-id]");
export const isDocumentList = (url) => url.pathname === OFFICE_PATH;
export const matchesDiscoveryPage = (response, query, cursor = null) => {
  const url = new URL(response.url());
  return isDocumentList(url) && response.request().method() === "GET" &&
    url.searchParams.get("query") === query && url.searchParams.get("cursor") === cursor;
};

export async function discoveryResponse(response) {
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const result = await response.json();
  expect(result.tenant_id).toBe(TENANT_ID);
  expect(result.page_size).toBe(50);
  expect(result.documents.length).toBeLessThanOrEqual(50);
  expect(result.has_more).toBe(result.next_cursor !== null);
  return result;
}

export async function openDiscovery(page, options = {}) {
  const result = await openOffice(page, { userId: DISCOVERY_EDITOR_ID, roleIds: "office-editor", ...options });
  expect(result.page_size).toBe(50);
  await expect(discoveryCards(page)).toHaveCount(result.documents.length);
  return result;
}

export async function searchDiscovery(page, query) {
  await showDocumentList(page);
  const pending = page.waitForResponse((response) => matchesDiscoveryPage(response, query.trim()));
  await page.locator("#documents-search").fill(query);
  await page.locator("#documents-search").press("Enter");
  const result = await discoveryResponse(await pending);
  await expect(page.locator("#documents-refresh")).toBeEnabled();
  await expect(discoveryCards(page)).toHaveCount(result.documents.length);
  return result;
}

export async function appendDiscovery(page, previous, count) {
  expect(previous.has_more).toBe(true);
  const query = (await page.locator("#documents-search").inputValue()).trim();
  const pending = page.waitForResponse((response) => matchesDiscoveryPage(response, query, previous.next_cursor));
  await page.locator("#documents-load-more").click();
  const result = await discoveryResponse(await pending);
  await expect(discoveryCards(page)).toHaveCount(count + result.documents.length);
  await expect(page.locator("#documents-refresh")).toBeEnabled();
  return result;
}

export async function discoveryPage(page, { query = "", cursor = null, headers = DISCOVERY_HEADERS, baseUrl = BASE_URL } = {}) {
  const parameters = new URLSearchParams({ query, page_size: "50" });
  if (cursor) parameters.set("cursor", cursor);
  return discoveryResponse(await page.request.get(`${baseUrl}${OFFICE_PATH}?${parameters}`, { headers }));
}

export async function holdDiscoveryPage(page, query) {
  let release;
  let started;
  let failStarted;
  let job;
  let request;
  const failures = new Map();
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve, reject) => { started = resolve; failStarted = reject; });
  const matches = (url) => isDocumentList(url) && url.searchParams.get("query") === query;
  const failed = (value) => { if (matches(new URL(value.url()))) failures.set(value, value.failure()?.errorText); };
  page.on("requestfailed", failed);
  const handler = (route) => {
    job = (async () => {
      request = route.request();
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      const body = await response.body();
      expect(response.status()).toBe(200);
      expect(JSON.parse(body.toString("utf8")).tenant_id).toBe(TENANT_ID);
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
      await expect.poll(() => failures.get(request), { message: "The obsolete list request must be canceled" }).toBe("net::ERR_ABORTED");
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
