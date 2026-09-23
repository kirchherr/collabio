import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, captureOfficeResponse, officeContent, officeContentPath,
  officeEditor, officeFeatures, openOffice, openOfficeDocument, setOfficeAcl, setOfficeFeatures,
} from "./office-support.mjs";
import { openComments } from "./office-review-support.mjs";
import {
  DISCOVERY_COUNT, DISCOVERY_HEADERS, DISCOVERY_READER_HEADERS, DISCOVERY_READER_ID,
  appendDiscovery, discoveryCards, discoveryPage, discoveryResponse, holdDiscoveryPage,
  isDocumentList, matchesDiscoveryPage, openDiscovery, searchDiscovery,
} from "./office-discovery-support.mjs";

const featureTest = test.extend({
  restoreDiscoveryFeatures: [async ({ request }, use) => {
    let previous = null;
    try { await use((features) => { previous = { ...features }; }); }
    finally { if (previous !== null) await setOfficeFeatures({ request }, previous); }
  }, { timeout: 20_000 }],
});

test("Office discovers all 225 real saved documents in stable unique pages even when a loaded title changes", async ({ page }) => {
  const first = await openDiscovery(page);
  expect(first.documents).toHaveLength(50);
  expect(first.can_create).toBe(true);
  const changed = first.documents[10];
  const original = await officeContent(page, changed.object_id, { headers: DISCOVERY_HEADERS });
  const saveTitle = async (title, versionId, suffix) => {
    const response = await page.request.post(`${BASE_URL}${OFFICE_PATH}/${changed.object_id}/versions`, {
      headers: DISCOVERY_HEADERS,
      data: { title, document: original.content, expected_current_version_id: versionId,
        mutation_reference: `discovery-order-${suffix}-${Date.now()}`, human_confirmation: true },
    });
    expect(response.status()).toBe(200);
    return response.json();
  };
  const renamed = await saveTitle("Discovery renamed while paging", original.version.version_id, "rename");
  try {
    let current = first;
    const documents = [...first.documents];
    while (current.has_more) {
      current = await appendDiscovery(page, current, documents.length);
      documents.push(...current.documents);
    }
    expect(documents).toHaveLength(DISCOVERY_COUNT);
    expect(new Set(documents.map((document) => document.object_id)).size).toBe(DISCOVERY_COUNT);
    for (let index = 1; index < documents.length; index += 1) {
      const before = documents[index - 1];
      const after = documents[index];
      expect(before.created_at_utc > after.created_at_utc ||
        (before.created_at_utc === after.created_at_utc && before.object_id > after.object_id)).toBe(true);
    }
    expect(documents.at(-1).title).toContain("Discovery 000");
    await expect(page.locator("#documents-status")).toHaveText("225 Dokumente geladen.");
    await expect(page.locator("#documents-load-more")).toBeHidden();
    const refreshed = page.waitForResponse((response) => matchesDiscoveryPage(response, ""));
    await page.locator("#documents-refresh").click();
    const updated = await discoveryResponse(await refreshed);
    expect(updated.documents.map((document) => document.object_id)).toEqual(first.documents.map((document) => document.object_id));
    expect(updated.documents[10].title).toBe("Discovery renamed while paging");
    expect(updated.documents[10].current_version_id).toBe(renamed.version.version_id);
  } finally { await saveTitle(original.version.title, renamed.version.version_id, "restore"); }
});

test("Office searches older saved titles with literal Unicode wildcards and hostile markup", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await openDiscovery(page);
  expect(first.documents.some((document) => document.title.startsWith("Discovery 00"))).toBe(false);
  const cases = [
    ["  café  ", ["Discovery 001 Café Straße 東京"]],
    ["Straße", ["Discovery 001 Café Straße 東京"]],
    ["STRASSE", ["Discovery 004 CAFE STRASSE 東京"]],
    ["東京", ["Discovery 004 CAFE STRASSE 東京", "Discovery 001 Café Straße 東京"]],
    ["100%", ["Discovery 002 literal 100%_path\\marker"]],
    ["_path", ["Discovery 002 literal 100%_path\\marker"]],
    ["\\marker", ["Discovery 002 literal 100%_path\\marker"]],
    ["<img", ['Discovery 000 <img src=x onerror=alert(260)> & literal']],
  ];
  for (const [query, titles] of cases) {
    const result = await searchDiscovery(page, query);
    expect(result.documents.map((document) => document.title)).toEqual(titles);
    expect(result.has_more).toBe(false);
    expect(result.can_create).toBe(true);
  }
  await expect(page.locator("#documents-list img, #documents-list script")).toHaveCount(0);
  const [objectId] = await discoveryCards(page).evaluateAll((cards) => cards.map((card) => card.dataset.documentId));
  const opened = await openOfficeDocument(page, objectId);
  expect(opened.version.content_hash).toMatch(/^sha256:/);
  await expect(officeEditor(page)).toHaveText("Synthetic discovery document 000.");
  const cleared = page.waitForResponse((response) => matchesDiscoveryPage(response, ""));
  await page.locator("#documents-clear").click();
  expect((await discoveryResponse(await cleared)).documents).toHaveLength(50);
  await expect(page.locator("#documents-search")).toHaveValue("");
  await expect(officeEditor(page)).toHaveText("Synthetic discovery document 000.");
  verifyBrowser();
});

test("Office filters current ACLs before page limits and preserves reader and create capabilities", async ({ page }) => {
  const hidden = (await discoveryPage(page)).documents[0];
  const allowed = await openDiscovery(page, {
    userId: DISCOVERY_READER_ID, roleIds: "office-reader", readableObjectIds: hidden.object_id,
  });
  expect(allowed.documents.map((document) => document.title.slice(0, 13))).toEqual(["Discovery 002", "Discovery 001", "Discovery 000"]);
  expect(allowed.has_more).toBe(false);
  expect(allowed.can_create).toBe(false);
  expect(allowed.documents.every((document) => document.can_write === false)).toBe(true);
  await expect(page.locator("#document-new")).toBeDisabled();
  const empty = await searchDiscovery(page, "Discovery 224");
  expect(empty.documents).toEqual([]);
  expect(empty.can_create).toBe(false);
  const denied = await page.request.get(`${BASE_URL}${officeContentPath(hidden.object_id)}`, { headers: { ...DISCOVERY_READER_HEADERS, "X-Readable-Object-Ids": hidden.object_id } });
  expect(denied.status()).toBe(404);
  expect(await denied.json()).toEqual({ detail: "Document not found" });
  const blocked = await openDiscovery(page, { baseUrl: BLOCKED_BASE_URL, userId: DISCOVERY_READER_ID, roleIds: "office-reader" });
  expect(blocked.documents).toHaveLength(3);
  expect(blocked.can_create).toBe(false);
  await openOfficeDocument(page, blocked.documents[2].object_id);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  await expect(page.locator("#document-save")).toBeDisabled();
});

featureTest("Office search append and fresh refresh preserve editor and review drafts while enforcing lost write permission", async ({ page, restoreDiscoveryFeatures }) => {
  const first = await openDiscovery(page);
  const saved = await openOfficeDocument(page, first.documents[0].object_id);
  await openComments(page, saved.document.object_id);
  await page.locator("#comment-new").click();
  await page.locator("#comment-body").fill("Unsaved discovery review draft");
  await officeEditor(page).fill("Unsaved discovery document draft");
  const writes = [];
  page.on("request", (request) => { if (request.method() === "POST" && new URL(request.url()).pathname.startsWith(OFFICE_PATH)) writes.push(request.url()); });
  const assertDrafts = async () => {
    await expect(officeEditor(page)).toHaveText("Unsaved discovery document draft");
    await expect(page.locator("#comment-body")).toHaveValue("Unsaved discovery review draft");
    await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
    await expect(page.locator("#discard-dialog")).toBeHidden();
    expect(writes).toEqual([]);
  };
  const filtered = await searchDiscovery(page, "Discovery 000");
  expect(filtered.documents.map((document) => document.object_id)).not.toContain(saved.document.object_id);
  await assertDrafts();
  const all = await searchDiscovery(page, "Discovery");
  await appendDiscovery(page, all, 50);
  await assertDrafts();
  const previous = await officeFeatures(page);
  restoreDiscoveryFeatures(previous);
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  const exact = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === officeContentPath(saved.document.object_id) && url.searchParams.get("version_id") === saved.version.version_id;
  });
  const listing = page.waitForResponse((response) => matchesDiscoveryPage(response, "Discovery"));
  await page.locator("#documents-refresh").click();
  expect((await (await exact).json()).can_write).toBe(false);
  expect((await discoveryResponse(await listing)).can_create).toBe(false);
  await assertDrafts();
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  await expect(page.locator("#document-save")).toBeDisabled();
  await setOfficeFeatures(page, previous);
  const restored = page.waitForResponse((response) => matchesDiscoveryPage(response, "Discovery"));
  await page.locator("#documents-refresh").click();
  expect((await discoveryResponse(await restored)).can_create).toBe(true);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await assertDrafts();
  expect((await officeContent(page, saved.document.object_id, { headers: DISCOVERY_HEADERS })).content).toEqual(saved.content);
});

test("Office absence from a filtered page preserves an open reader but fresh revoked access clears it", async ({ page }) => {
  const source = (await discoveryPage(page, { query: "Discovery 224" })).documents[0];
  await setOfficeAcl(page, source.object_id);
  try {
    await openOffice(page, { userId: OFFICE_READER_ID, roleIds: "office-reader" });
    await searchDiscovery(page, "Discovery 224");
    const saved = await openOfficeDocument(page, source.object_id);
    await searchDiscovery(page, "No matching discovery document");
    await expect(officeEditor(page)).toHaveText("Synthetic discovery document 224.");
    await setOfficeAcl(page, source.object_id, { status: "revoked" });
    const matches = (url) => url.pathname === officeContentPath(source.object_id) && url.searchParams.get("version_id") === saved.version.version_id;
    const captured = await captureOfficeResponse(page, matches);
    const pending = page.waitForResponse((response) => matches(new URL(response.url())));
    await page.locator("#documents-refresh").click();
    const response = await pending;
    expect(response.status()).toBe(404);
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect((await captured.received).json.detail).toBe("Document not found");
    await expect(page.locator("#documents-status")).toContainText("nicht mehr freigegeben");
    await expect(officeEditor(page)).toHaveCount(0);
    await expect(discoveryCards(page)).toHaveCount(0);
  } finally { await setOfficeAcl(page, source.object_id, { status: "revoked" }); }
});

test("Office cancels obsolete searches and context responses without restoring old titles", async ({ page }) => {
  await openDiscovery(page);
  const held = await holdDiscoveryPage(page, "Discovery 000");
  try {
    await page.locator("#documents-search").fill("Discovery 000");
    await page.locator("#documents-search").press("Enter");
    await held.ready;
    await searchDiscovery(page, "Discovery 001");
    await page.evaluate(() => {
      window.staleDiscovery = false;
      new MutationObserver(() => { window.staleDiscovery ||= document.querySelector("#documents-list").textContent.includes("Discovery 000"); })
        .observe(document.querySelector("#documents-list"), { childList: true, subtree: true, characterData: true });
    });
    await held.finishCancelled();
    await expect(discoveryCards(page)).toHaveCount(1);
    await expect(discoveryCards(page)).toContainText("Discovery 001");
    expect(await page.evaluate(() => window.staleDiscovery)).toBe(false);
  } finally { await held.dispose(); }
  const contextRead = await holdDiscoveryPage(page, "Discovery 220");
  try {
    await page.locator("#documents-search").fill("Discovery 220");
    await page.locator("#documents-search").press("Enter");
    await contextRead.ready;
    const changed = page.waitForResponse((response) => matchesDiscoveryPage(response, ""));
    await page.evaluate((userId) => {
      document.querySelector("#user-id").value = userId;
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }, DISCOVERY_READER_ID);
    expect((await discoveryResponse(await changed)).documents).toHaveLength(3);
    await contextRead.finishCancelled();
    await expect(discoveryCards(page)).toHaveCount(3);
    await expect(page.locator("#documents-list")).not.toContainText("Discovery 220");
    await expect(page.locator("#document-new")).toBeDisabled();
  } finally { await contextRead.dispose(); }
});

test("Office retains loaded pages and draft after a lost real list response then retries the same cursor", async ({ page }) => {
  const first = await openDiscovery(page);
  await openOfficeDocument(page, first.documents[0].object_id);
  await officeEditor(page).fill("Local draft survives unavailable pagination");
  const attempts = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (isDocumentList(url) && url.searchParams.has("cursor")) attempts.push(url.href);
  });
  let upstream;
  await page.route((url) => isDocumentList(url) && url.searchParams.get("cursor") === first.next_cursor, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    upstream = await discoveryResponse(response);
    await route.abort("failed");
  }, { times: 1 });
  await page.locator("#documents-load-more").click();
  await expect(page.locator("#documents-retry")).toBeVisible();
  await expect(page.locator("#documents-status")).toContainText("Die bisherige Liste und Ihre Entwürfe bleiben erhalten");
  expect(upstream.documents).toHaveLength(50);
  await expect(discoveryCards(page)).toHaveCount(50);
  await expect(officeEditor(page)).toHaveText("Local draft survives unavailable pagination");
  const retry = page.waitForResponse((response) => matchesDiscoveryPage(response, "", first.next_cursor));
  await page.locator("#documents-retry").click();
  const recovered = await discoveryResponse(await retry);
  expect(recovered.documents).toEqual(upstream.documents);
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toBe(attempts[0]);
  await expect(discoveryCards(page)).toHaveCount(100);
  await expect(officeEditor(page)).toHaveText("Local draft survives unavailable pagination");
  await expect(page.locator("#discard-dialog")).toBeHidden();
});

test("Office rejects tampered or cross-context cursors and restarts the list without discarding an open draft", async ({ page }) => {
  const first = await openDiscovery(page);
  await openOfficeDocument(page, first.documents[0].object_id);
  await officeEditor(page).fill("Draft survives cursor restart");
  const parameters = new URLSearchParams({ query: "", page_size: "50", cursor: first.next_cursor });
  const crossContext = await page.request.get(`${BASE_URL}${OFFICE_PATH}?${parameters}`, { headers: { ...DISCOVERY_HEADERS, "X-Role-Ids": "office-reader" } });
  expect(crossContext.status()).toBe(400);
  expect(await crossContext.json()).toEqual({ detail: "Invalid document list request" });
  let captured;
  await page.route((url) => isDocumentList(url) && url.searchParams.get("cursor") === first.next_cursor, async (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set("cursor", `${first.next_cursor}tampered`);
    const response = await route.fetch({ url: url.href, maxRetries: 0, maxRedirects: 0 });
    const body = await response.body();
    captured = { status: response.status(), json: JSON.parse(body.toString("utf8")) };
    await route.fulfill({ response, body });
  }, { times: 1 });
  const rejected = page.waitForResponse((response) => matchesDiscoveryPage(response, "", first.next_cursor));
  await page.locator("#documents-load-more").click();
  const response = await rejected;
  expect(response.status()).toBe(400);
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect(captured).toEqual({ status: 400, json: { detail: "Invalid document list request" } });
  await expect(page.locator("#documents-retry")).toHaveText("Liste neu laden");
  await expect(discoveryCards(page)).toHaveCount(0);
  await expect(officeEditor(page)).toHaveText("Draft survives cursor restart");
  const restarted = page.waitForResponse((result) => matchesDiscoveryPage(result, ""));
  await page.locator("#documents-retry").click();
  expect((await discoveryResponse(await restarted)).documents).toEqual(first.documents);
  await expect(discoveryCards(page)).toHaveCount(50);
  await expect(officeEditor(page)).toHaveText("Draft survives cursor restart");
  const empty = await searchDiscovery(page, "No matching discovery document");
  expect(empty.documents).toEqual([]);
  expect(empty.can_create).toBe(true);
  await expect(page.locator("#document-new")).toBeEnabled();
});
