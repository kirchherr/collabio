import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, captureOfficeResponse, loadOfficeComparison, officeContent,
  officeContentPath, officeEditor, openOffice, openOfficeDocument, saveOffice, setOfficeAcl,
} from "./office-support.mjs";
import { openComments } from "./office-review-support.mjs";
import { openSuggestions, prepareSuggestion } from "./office-suggestion-support.mjs";
import {
  HISTORY_HEADERS, HISTORY_READER_ID, allHistory, appendAllHistory, appendHistory, historyPage,
  historyPath, historyResponse, historyRows, holdHistoryPage, matchesHistoryPage,
  openHistoryComparison, openHistoryFixture, openHistoryPanel, prepareHistoryHead, saveHistoryVersion,
} from "./office-history-pagination-support.mjs";

const aclTest = test.extend({
  revokeTemporaryHistoryReader: [async ({ request }, use) => {
    let objectId = null;
    try { await use((value) => { objectId = value; }); }
    finally { if (objectId) await setOfficeAcl({ request }, objectId, { status: "revoked" }); }
  }, { timeout: 20_000 }],
});

function collectHistoryWrites(page) {
  const writes = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.startsWith(OFFICE_PATH)) writes.push(request.postDataJSON());
  });
  return writes;
}

async function expectOriginalVersion(page) {
  await expect(officeEditor(page).locator("h2")).toHaveText("History 001 — Café 😀");
  await expect(officeEditor(page).locator("strong")).toHaveText("<script>literal earliest version</script>");
  await expect(officeEditor(page).locator("table th")).toHaveCount(2);
  await expect(officeEditor(page).locator("table")).toContainText("Original decision");
  await expect(officeEditor(page).locator("script, img")).toHaveCount(0);
  await expect(page.locator("#document-title")).toHaveValue("History 001 Café 😀 <img src=x>");
}

test("Office loads the complete genuine history beyond 200 and reads the immutable earliest rich version", async ({ page }) => {
  const { objectId, first } = await openHistoryFixture(page);
  expect(first.versions).toHaveLength(50);
  expect(first.has_more).toBe(true);
  const writes = collectHistoryWrites(page);
  const versions = await appendAllHistory(page, objectId, first);
  await expect(historyRows(page)).toHaveCount(versions.length);
  expect(await historyRows(page).evaluateAll((rows) => rows.map((row) => row.dataset.versionId))).toEqual(versions.map((version) => version.version_id));
  await expect(page.locator("#history-more")).toBeHidden();
  await expect(page.locator("#history-status")).not.toContainText("ältere Fassungen sind nicht geladen");
  const earliest = versions.at(-1);
  const pending = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === officeContentPath(objectId) && url.searchParams.get("version_id") === earliest.version_id;
  });
  await page.locator(`[data-version-id="${earliest.version_id}"]`).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const content = await response.json();
  expect(content.version.content_hash).toBe(earliest.content_hash);
  expect(content.version.source_write_receipt_hash).toBe(earliest.source_write_receipt_hash);
  expect(content.is_current_version).toBe(false);
  await expectOriginalVersion(page);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  expect(writes).toEqual([]);
});

test("Office comparison keeps selections and results across older pages and refresh then confirms an earliest-version successor", async ({ page }) => {
  await prepareHistoryHead(page, "Current target for an old saved version", "History takeover current target");
  const { objectId, saved } = await openHistoryFixture(page);
  const first = await openHistoryComparison(page, objectId);
  const selectedLeft = first.versions[1].version_id;
  const selectedRight = first.versions[0].version_id;
  await loadOfficeComparison(page, objectId, selectedLeft, selectedRight);
  const beforeAppend = await page.locator("#compare-results").textContent();
  const versions = await appendAllHistory(page, objectId, first, { comparison: true });
  await expect(page.locator("#compare-left")).toHaveValue(selectedLeft);
  await expect(page.locator("#compare-right")).toHaveValue(selectedRight);
  await expect(page.locator("#compare-results")).toHaveText(beforeAppend);
  const earliest = versions.at(-1);
  await loadOfficeComparison(page, objectId, earliest.version_id, saved.version.version_id);
  const resultText = await page.locator("#compare-results .compare-text").allTextContents();
  await expect(page.locator("#compare-results")).toContainText("Original decision");
  const refreshed = page.waitForResponse((response) => matchesHistoryPage(response, objectId));
  await page.locator("#compare-history-refresh").click();
  expect((await historyResponse(await refreshed, objectId)).versions).toHaveLength(50);
  await expect(page.locator("#compare-left")).toHaveValue(earliest.version_id);
  await expect(page.locator("#compare-left option:checked")).toContainText("außerhalb der geladenen Liste");
  expect(await page.locator("#compare-results .compare-text").allTextContents()).toEqual(resultText);
  const original = await officeContent(page, objectId, { headers: HISTORY_HEADERS, versionId: earliest.version_id });
  const writes = collectHistoryWrites(page);
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(page.locator("#document-notice")).toContainText("ungespeicherten Entwurf übernommen");
  await expectOriginalVersion(page);
  expect(writes).toEqual([]);
  expect((await allHistory(page, objectId)).versions.map((version) => version.version_id)).toEqual(versions.map((version) => version.version_id));
  const committed = await saveOffice(page, { objectId });
  expect(committed.version.previous_version_id).toBe(saved.version.version_id);
  expect(committed.content).toEqual(original.content);
  expect(committed.version.title).toBe(original.version.title);
  expect(writes).toHaveLength(1);
  expect(writes[0].human_confirmation).toBe(true);
  expect(writes[0].expected_current_version_id).toBe(saved.version.version_id);
  const after = await allHistory(page, objectId);
  expect(after.versions.map((version) => version.version_id)).toEqual([committed.version.version_id, ...versions.map((version) => version.version_id)]);
  expect((await officeContent(page, objectId, { headers: HISTORY_HEADERS, versionId: earliest.version_id })).content).toEqual(original.content);
});

test("Office ordinary readers load and compare versions beyond 200 with the write feature closed", async ({ page }) => {
  const { objectId, saved } = await openHistoryFixture(page, { baseUrl: BLOCKED_BASE_URL, userId: HISTORY_READER_ID, roleIds: "office-reader" });
  expect(saved.can_write).toBe(false);
  const writes = collectHistoryWrites(page);
  const first = await openHistoryComparison(page, objectId);
  const versions = await appendAllHistory(page, objectId, first, { comparison: true });
  await loadOfficeComparison(page, objectId, versions.at(-1).version_id, versions[0].version_id);
  await expect(page.locator("#compare-results")).toContainText("Original decision");
  await expect(page.locator("#compare-restore")).toBeDisabled();
  await page.locator("#compare-close").click();
  await page.locator(`[data-version-id="${versions.at(-1).version_id}"]`).click();
  await expectOriginalVersion(page);
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator("#document-restore")).toBeHidden();
  expect(writes).toEqual([]);
});

test("Office keeps the loaded history head and local document and review drafts across a concurrent save and refresh", async ({ page }) => {
  const { objectId, saved } = await openHistoryFixture(page);
  await openComments(page, objectId);
  await page.locator("#comment-new").click();
  await page.locator("#comment-body").fill("History review draft remains local");
  // Use the editor's keyboard replacement for the rich fixture (including a table).
  // Direct contenteditable fill can leave an invalid empty table in Chromium.
  await officeEditor(page).press("Control+a");
  await page.keyboard.insertText("History document draft remains local");
  await expect(officeEditor(page)).toHaveText("History document draft remains local");
  await expect(page.locator("#document-save")).toBeEnabled();
  const first = await openHistoryPanel(page, objectId);
  const newer = await saveHistoryVersion(page, saved, "Concurrent new history head", "History concurrent saved title");
  const writes = collectHistoryWrites(page);
  const second = await appendHistory(page, objectId, first);
  expect(second.history_head_version_id).toBe(saved.version.version_id);
  expect(second.current_version_id).toBe(newer.version.version_id);
  await expect(historyRows(page)).toHaveCount(100);
  await expect(page.locator("#history-status")).toContainText("Eine neuere Fassung ist verfügbar");
  await expect(page.locator(`[data-version-id="${saved.version.version_id}"] strong`)).toContainText("Geladener Stand");
  await expect(page.locator(`[data-version-id="${newer.version.version_id}"]`)).toHaveCount(0);
  const refresh = page.waitForResponse((response) => matchesHistoryPage(response, objectId));
  await page.locator("#history-refresh").click();
  expect((await historyResponse(await refresh, objectId)).history_head_version_id).toBe(newer.version.version_id);
  await expect(historyRows(page)).toHaveCount(50);
  await expect(historyRows(page).first()).toHaveAttribute("data-version-id", newer.version.version_id);
  await expect(officeEditor(page)).toHaveText("History document draft remains local");
  await expect(page.locator("#comment-body")).toHaveValue("History review draft remains local");
  await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
  await expect(page.locator("#discard-dialog")).toBeHidden();
  await page.locator("#comments-tab").click();
  await expect(page.locator("#comment-body")).toBeVisible();
  await expect(page.locator("#comment-body")).toHaveValue("History review draft remains local");
  await page.locator("#document-close").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(officeEditor(page)).toHaveText("History document draft remains local");
  await expect(page.locator("#comment-body")).toHaveValue("History review draft remains local");
  expect(writes).toEqual([]);
  await page.locator("#document-close").click();
  await page.locator("#discard-confirm").click();
  await openHistoryFixture(page);
  await openSuggestions(page, objectId);
  await prepareSuggestion(page, "Concurrent new history head", "History suggestion draft remains local");
  await page.locator("#suggestion-confirm-cancel").click();
  const suggestionHistory = await openHistoryPanel(page, objectId);
  await appendHistory(page, objectId, suggestionHistory);
  const suggestionRefresh = page.waitForResponse((response) => matchesHistoryPage(response, objectId));
  await page.locator("#history-refresh").click();
  await historyResponse(await suggestionRefresh, objectId);
  await page.locator("#suggestions-tab").click();
  await expect(page.locator("#suggestion-replacement")).toBeVisible();
  await expect(page.locator("#suggestion-replacement")).toHaveValue("History suggestion draft remains local");
  await page.locator("#document-close").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(page.locator("#suggestion-replacement")).toHaveValue("History suggestion draft remains local");
  expect(writes).toEqual([]);
});

test("Office takeover beyond 200 preserves its draft when a later writer wins the confirmed CAS save", async ({ page }) => {
  await prepareHistoryHead(page, "Current source before history conflict", "History conflict base");
  const { objectId, saved, first } = await openHistoryFixture(page);
  const versions = await appendAllHistory(page, objectId, first);
  const earliest = versions.at(-1);
  await page.locator(`[data-version-id="${earliest.version_id}"]`).click();
  await expectOriginalVersion(page);
  await page.locator("#document-restore").click();
  await expect(page.locator("#document-notice")).toContainText("ungespeicherten Entwurf übernommen");
  const winner = await saveHistoryVersion(page, saved, "History concurrent winner survives", "History winner title");
  const conflict = await saveOffice(page, { objectId, status: 409 });
  expect(conflict.detail).toBe("The document has a newer or conflicting saved version");
  await expectOriginalVersion(page);
  await expect(page.locator("#document-notice")).toContainText("neuere Version");
  expect((await officeContent(page, objectId, { headers: HISTORY_HEADERS })).version.version_id).toBe(winner.version.version_id);
  const after = await allHistory(page, objectId);
  expect(after.versions.map((version) => version.version_id)).toEqual([winner.version.version_id, ...versions.map((version) => version.version_id)]);
});

aclTest("Office rechecks parent ACLs on older-history requests and rejects a cursor from another role context", async ({ page, revokeTemporaryHistoryReader }) => {
  const { objectId, saved, first } = await openHistoryFixture(page);
  const parameters = new URLSearchParams({ page_size: "50", cursor: first.next_cursor });
  const wrongRoles = await page.request.get(`${BASE_URL}${historyPath(objectId)}?${parameters}`, { headers: { ...HISTORY_HEADERS, "X-Role-Ids": "office-reader" } });
  expect(wrongRoles.status()).toBe(400);
  expect(await wrongRoles.json()).toEqual({ detail: "Invalid version history request" });
  revokeTemporaryHistoryReader(objectId);
  await setOfficeAcl(page, objectId);
  await openOffice(page, { userId: OFFICE_READER_ID, roleIds: "office-reader" });
  const search = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === OFFICE_PATH && url.searchParams.get("query") === saved.document.title;
  });
  await page.locator("#documents-search").fill(saved.document.title);
  await page.locator("#documents-search").press("Enter");
  expect((await search).status()).toBe(200);
  await openOfficeDocument(page, objectId);
  const readerFirst = await openHistoryPanel(page, objectId);
  await setOfficeAcl(page, objectId, { status: "revoked" });
  const matches = (url) => url.pathname === historyPath(objectId) && url.searchParams.get("cursor") === readerFirst.next_cursor;
  const captured = await captureOfficeResponse(page, matches);
  const pending = page.waitForResponse((response) => matches(new URL(response.url())));
  await page.locator("#history-more").click();
  const response = await pending;
  expect(response.status()).toBe(404);
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect((await captured.received).json.detail).toBe("Document not found");
  await expect(page.locator("#documents-status")).toContainText("nicht mehr freigegeben");
  await expect(officeEditor(page)).toHaveCount(0);
  await expect(historyRows(page)).toHaveCount(0);
});

test("Office retries a lost genuine history page and restarts a rejected cursor while preserving selection and draft", async ({ page }) => {
  const { objectId, first } = await openHistoryFixture(page);
  await officeEditor(page).fill("Unsaved history retry draft");
  const attempts = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === historyPath(objectId) && url.searchParams.get("cursor") === first.next_cursor) attempts.push(url.href);
  });
  let upstream;
  await page.route((url) => url.pathname === historyPath(objectId) && url.searchParams.get("cursor") === first.next_cursor, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    upstream = await historyResponse(response, objectId);
    await route.abort("failed");
  }, { times: 1 });
  await page.locator("#history-more").click();
  await expect(page.locator("#history-retry")).toBeVisible();
  await expect(historyRows(page)).toHaveCount(50);
  await expect(officeEditor(page)).toHaveText("Unsaved history retry draft");
  const retry = page.waitForResponse((response) => matchesHistoryPage(response, objectId, first.next_cursor));
  await page.locator("#history-retry").click();
  const second = await historyResponse(await retry, objectId);
  expect(second.versions).toEqual(upstream.versions);
  expect(attempts).toHaveLength(2);
  expect(attempts[0]).toBe(attempts[1]);
  await expect(historyRows(page)).toHaveCount(100);
  let rejected;
  await page.route((url) => url.pathname === historyPath(objectId) && url.searchParams.get("cursor") === second.next_cursor, async (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set("cursor", `${second.next_cursor}tampered`);
    const response = await route.fetch({ url: url.href, maxRetries: 0, maxRedirects: 0 });
    const body = await response.body();
    rejected = { status: response.status(), json: JSON.parse(body.toString("utf8")) };
    await route.fulfill({ response, body });
  }, { times: 1 });
  const invalid = page.waitForResponse((response) => matchesHistoryPage(response, objectId, second.next_cursor));
  await page.locator("#history-more").click();
  const response = await invalid;
  expect(response.status()).toBe(400);
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect(rejected).toEqual({ status: 400, json: { detail: "Invalid version history request" } });
  await expect(page.locator("#history-retry")).toHaveText("Versionsliste neu laden");
  await expect(historyRows(page)).toHaveCount(100);
  const restarted = page.waitForResponse((result) => matchesHistoryPage(result, objectId));
  await page.locator("#history-retry").click();
  expect((await historyResponse(await restarted, objectId)).versions).toEqual(first.versions);
  await expect(historyRows(page)).toHaveCount(50);
  await expect(officeEditor(page)).toHaveText("Unsaved history retry draft");
  await expect(page.locator("#discard-dialog")).toBeHidden();
});

test("Office ignores late older-version pages after comparison close or a changed principal", async ({ page }) => {
  const { objectId, saved } = await openHistoryFixture(page);
  const first = await openHistoryComparison(page, objectId);
  const held = await holdHistoryPage(page, objectId, first.next_cursor);
  try {
    await page.locator("#compare-history-more").click();
    await held.ready;
    await page.locator("#compare-close").click();
    await expect(page.locator("#compare-dialog")).toBeHidden();
    await held.finishCancelled();
    await expect(page.locator("#compare-results")).toHaveText("");
    await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
    await expect(historyRows(page)).toHaveCount(50);
  } finally { await held.dispose(); }
  for (const action of ["inspector", "tab", "focus"]) {
    const before = await openHistoryPanel(page, objectId);
    const pending = await holdHistoryPage(page, objectId, before.next_cursor);
    try {
      await page.locator("#history-more").click();
      await pending.ready;
      await page.locator(action === "inspector" ? "#inspector-toggle" : action === "tab" ? "#outline-tab" : "#focus-toggle").click();
      await pending.finishCancelled();
      await expect(historyRows(page)).toHaveCount(50);
      await expect(page.locator("#history-status")).not.toContainText("werden geladen");
      await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
      if (action === "focus") await page.locator("#focus-toggle").click();
    } finally { await pending.dispose(); }
  }
  const current = await openHistoryPanel(page, objectId);
  const contextRead = await holdHistoryPage(page, objectId, current.next_cursor);
  try {
    await page.locator("#history-more").click();
    await contextRead.ready;
    const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    await page.evaluate((userId) => {
      document.querySelector("#user-id").value = userId;
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }, HISTORY_READER_ID);
    expect((await changed).status()).toBe(200);
    await contextRead.finishCancelled();
    await expect(officeEditor(page)).toHaveCount(0);
    await expect(historyRows(page)).toHaveCount(0);
    await expect(page.locator("#compare-results")).toHaveText("");
  } finally { await contextRead.dispose(); }
});
