import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_HEADERS, OFFICE_PATH, OFFICE_READER_HEADERS, OFFICE_READER_ID,
  captureOfficeResponse, createOfficeDocument, loadOfficeComparison, newOfficeDraft, officeContent,
  officeEditor, officeFeatures, officeVersions, openOffice, openOfficeComparison,
  openOfficeDocument, saveOffice, setOfficeAcl, setOfficeFeatures, textDocument,
} from "./office-support.mjs";
import {
  collectSuggestionWrites, confirmSuggestion, createSuggestion, holdSuggestionRead,
  observeStaleSuggestion, openSuggestion, openSuggestions, prepareSuggestion,
  prepareSuggestionDecision, readSuggestion, readSuggestions, refreshSuggestions,
  suggestionCard, suggestionPath,
} from "./office-suggestion-support.mjs";

const featureTest = test.extend({
  restoreOfficeFeatures: [async ({ request }, use) => {
    let previous = null;
    try { await use((features) => { previous = { ...features }; }); }
    finally { if (previous !== null) await setOfficeFeatures({ request }, previous); }
  }, { timeout: 20_000 }],
});

async function openHistorical(page, objectId, versionId) {
  if (!await page.locator("#history-tab").isVisible()) await page.locator("#inspector-toggle").click();
  await page.locator("#history-tab").click();
  const pending = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `${OFFICE_PATH}/${objectId}/content` && url.searchParams.get("version_id") === versionId;
  });
  await page.locator(`[data-version-id="${versionId}"]`).click();
  expect((await pending).status()).toBe(200);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
}

test("Office confirms a literal Unicode suggestion and atomically saves its accepted text with marks and immutable history", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic accepted suggestion", { text: "Before " });
  await officeEditor(page).press("Control+End");
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.insertText("😀 Ca");
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.insertText("fé e\u0301 after");
  const first = await saveOffice(page);
  const objectId = first.document.object_id;
  const writes = collectSuggestionWrites(page);
  const replacement = '<img src="https://suggestion.invalid/leak" onerror="window.suggestionExecuted=true"> 茶';
  await openSuggestions(page, objectId);
  await prepareSuggestion(page, "😀 Café e\u0301", replacement);
  expect(writes).toHaveLength(0);
  await page.locator("#suggestion-confirm-cancel").click();
  await expect(page.locator("#suggestion-replacement")).toHaveValue(replacement);
  expect((await readSuggestions(page, objectId)).suggestions).toEqual([]);
  await page.locator("#suggestion-prepare").click();
  const created = await confirmSuggestion(page, objectId);
  const suggestionId = created.suggestion.suggestion_id;
  expect(created.quote).toBe("😀 Café e\u0301");
  expect(created.suggestion.anchor).toEqual({ from: 8, to: 8 + "😀 Café e\u0301".length });
  expect(created.suggestion.anchor_version_id).toBe(first.version.version_id);
  expect(created.document_result).toBeNull();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await openSuggestion(page, objectId, suggestionId);
  await expect(page.locator("#suggestion-after")).toHaveText(replacement);
  await expect(page.locator("#suggestions-panel img, #suggestions-panel script")).toHaveCount(0);
  await prepareSuggestionDecision(page, suggestionId, "accept");
  await page.locator("#suggestion-confirm-cancel").click();
  expect(writes).toHaveLength(1);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await prepareSuggestionDecision(page, suggestionId, "accept");
  const accepted = await confirmSuggestion(page, objectId, { suggestionId });
  const second = accepted.document_result;
  expect(accepted.suggestion.status).toBe("accepted");
  expect(accepted.suggestion.revision).toBe(2);
  expect(accepted.suggestion.result_version_id).toBe(second.version.version_id);
  expect(second.version.previous_version_id).toBe(first.version.version_id);
  expect(second.content.content[0].content).toEqual([
    { type: "text", text: "Before " },
    { type: "text", text: replacement, marks: [{ type: "bold" }] },
    { type: "text", text: " after" },
  ]);
  expect(writes).toHaveLength(2);
  expect(writes.every(({ body }) => body.human_confirmation === true)).toBe(true);
  await expect(officeEditor(page)).toHaveText(`Before ${replacement} after`);
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await page.evaluate(() => window.suggestionExecuted)).toBeUndefined();
  expect((await officeContent(page, objectId, { versionId: first.version.version_id })).content).toEqual(first.content);
  await openOffice(page);
  await openOfficeDocument(page, objectId);
  await expect(officeEditor(page)).toHaveText(`Before ${replacement} after`);
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.result_version_id).toBe(second.version.version_id);
  verifyBrowser();
});

test("Office rejection leaves the document untouched and a separately confirmed empty replacement deletes only its anchor", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic rejected and deletion suggestions", "Keep remove keep");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const proposal = await createSuggestion(page, objectId, "remove", "");
  const suggestionId = proposal.suggestion.suggestion_id;
  await openSuggestion(page, objectId, suggestionId);
  await prepareSuggestionDecision(page, suggestionId, "reject");
  await page.locator("#suggestion-confirm-cancel").click();
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
  await prepareSuggestionDecision(page, suggestionId, "reject");
  const rejected = await confirmSuggestion(page, objectId, { suggestionId });
  expect(rejected.suggestion.status).toBe("rejected");
  expect(rejected.suggestion.result_version_id).toBeNull();
  expect(rejected.document_result).toBeNull();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  expect((await officeContent(page, objectId)).content).toEqual(first.content);
  await openSuggestion(page, objectId, suggestionId);
  await expect(suggestionCard(page, suggestionId).locator('[data-suggestion-action="accept"]')).toBeDisabled();
  const deletion = await createSuggestion(page, objectId, "remove", "");
  const deletionId = deletion.suggestion.suggestion_id;
  await openSuggestion(page, objectId, deletionId);
  await prepareSuggestionDecision(page, deletionId, "accept");
  const accepted = await confirmSuggestion(page, objectId, { suggestionId: deletionId });
  expect(accepted.document_result.content.content[0].content.map((part) => part.text || "").join("")).toBe("Keep  keep");
  await expect(officeEditor(page)).toHaveText("Keep  keep");
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("rejected");
});

test("Office concurrent document saves conflict after acceptance preparation and historical proposals remain rejectable", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic stale suggestion", "Original selected wording");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const created = await createSuggestion(page, objectId, "selected", "proposed");
  const suggestionId = created.suggestion.suggestion_id;
  await openSuggestion(page, objectId, suggestionId);
  await prepareSuggestionDecision(page, suggestionId, "accept");
  const concurrent = await page.request.post(`${BASE_URL}${OFFICE_PATH}/${objectId}/versions`, {
    headers: OFFICE_HEADERS,
    data: { title: first.document.title, document: textDocument("Concurrent saved wording"), expected_current_version_id: first.version.version_id, mutation_reference: `synthetic-suggestion-save-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(concurrent.status()).toBe(200);
  const second = await concurrent.json();
  await confirmSuggestion(page, objectId, { suggestionId, status: 409 });
  await expect(page.locator("#suggestions-status")).toContainText("Stand hat sich geändert");
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
  expect((await officeContent(page, objectId)).version.version_id).toBe(second.version.version_id);
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  await openOffice(page);
  await openOfficeDocument(page, objectId);
  await openHistorical(page, objectId, first.version.version_id);
  await openSuggestions(page, objectId);
  const historical = await openSuggestion(page, objectId, suggestionId);
  expect(historical.suggestion.can_accept).toBe(false);
  expect(historical.suggestion.can_reject).toBe(true);
  await expect(page.locator("#suggestion-new")).toBeDisabled();
  await expect(suggestionCard(page, suggestionId).locator('[data-suggestion-action="accept"]')).toBeDisabled();
  await prepareSuggestionDecision(page, suggestionId, "reject");
  await confirmSuggestion(page, objectId, { suggestionId });
  await expect(officeEditor(page)).toHaveText("Original selected wording");
  await openOfficeComparison(page);
  await loadOfficeComparison(page, objectId, first.version.version_id, second.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("Original selected wording");
  await expect(page.locator("#compare-results")).toContainText("Concurrent saved wording");
  expect(await officeVersions(page, objectId)).toHaveLength(2);
});

test("Office readers inspect suggestions while forged, foreign and revoked parent rights fail closed", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic suggestion authorization", "Protected original text");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const created = await createSuggestion(page, objectId, "original", "Protected proposal secret");
  const suggestionId = created.suggestion.suggestion_id;
  await setOfficeAcl(page, objectId);
  await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(page, objectId);
  await openSuggestions(page, objectId);
  const read = await openSuggestion(page, objectId, suggestionId);
  expect(read.suggestion.can_accept).toBe(false);
  expect(read.suggestion.can_reject).toBe(false);
  await expect(page.locator("#suggestion-new")).toBeDisabled();
  for (const action of ["accept", "reject"]) await expect(suggestionCard(page, suggestionId).locator(`[data-suggestion-action="${action}"]`)).toBeDisabled();
  const deniedWrite = await page.request.post(`${BASE_URL}${suggestionPath(objectId, suggestionId)}/decisions`, {
    headers: OFFICE_READER_HEADERS,
    data: { operation: "accept", expected_revision: 1, expected_current_version_id: first.version.version_id, mutation_reference: `synthetic-denied-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(deniedWrite.status()).toBe(403);
  for (const headers of [
    { ...OFFICE_HEADERS, "X-User-Id": "work-assignee-e2e", "X-Readable-Object-Ids": `${objectId},${suggestionId}` },
    { ...OFFICE_HEADERS, "X-Tenant-Id": "tenant-work-e2e-foreign", "X-Readable-Object-Ids": `${objectId},${suggestionId}` },
  ]) {
    const denied = await page.request.get(`${BASE_URL}${suggestionPath(objectId, suggestionId)}`, { headers });
    expect([403, 404, 423]).toContain(denied.status());
    expect(await denied.text()).not.toContain("Protected proposal secret");
  }
  await setOfficeAcl(page, objectId, { status: "revoked" });
  await refreshSuggestions(page, objectId, 404);
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#suggestions-list")).toHaveText("");
  await expect(page.locator("#office-editor")).toHaveText("");
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});

test("Office proposal storage failures and a lost successful acceptance retry exactly without duplicate versions", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic suggestion exact retry", "Original retry wording");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const writes = collectSuggestionWrites(page);
  await prepareSuggestion(page, "Original", "Accepted");
  await confirmSuggestion(page, objectId, { status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  await expect(page.locator("#suggestion-replacement")).toHaveValue("Accepted");
  await expect(page.locator("#suggestion-prepare")).toContainText("Speicherung prüfen");
  expect((await readSuggestions(page, objectId)).suggestions).toEqual([]);
  await page.locator("#suggestion-prepare").click();
  const created = await confirmSuggestion(page, objectId);
  expect(writes[1]).toEqual(writes[0]);
  const suggestionId = created.suggestion.suggestion_id;
  await openSuggestion(page, objectId, suggestionId);
  const failedRead = await captureOfficeResponse(page, (url) => url.pathname === suggestionPath(objectId, suggestionId), { extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  await suggestionCard(page, suggestionId).locator('[data-suggestion-action="open"]').click();
  const unavailable = await failedRead.received;
  expect(unavailable.status).toBe(503);
  expect(unavailable.headers["cache-control"]).toContain("no-store");
  expect(unavailable.json.detail).toBe("Office storage unavailable");
  await expect(page.locator("#suggestion-detail")).toBeHidden();
  await expect(page.locator("#suggestions-panel")).not.toContainText("Accepted");
  await openSuggestion(page, objectId, suggestionId);
  await prepareSuggestionDecision(page, suggestionId, "accept");
  await confirmSuggestion(page, objectId, { suggestionId, status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
  await page.locator("#suggestion-prepare").click();
  let deliver;
  const committed = new Promise((resolve) => { deliver = resolve; });
  await page.route((url) => url.pathname === `${suggestionPath(objectId, suggestionId)}/decisions`, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.suggestion.status).toBe("accepted");
    await route.abort("failed");
    deliver(result);
  }, { times: 1 });
  await page.locator("#suggestion-confirm-checkbox").check();
  await page.locator("#suggestion-confirm-submit").click();
  const saved = await committed;
  await expect(page.locator("#suggestion-confirm-dialog")).toBeHidden();
  await expect(page.locator("#suggestion-prepare")).toContainText("Speicherung prüfen");
  await expect(officeEditor(page)).toHaveText("Original retry wording");
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  await page.locator("#suggestion-prepare").click();
  const replay = await confirmSuggestion(page, objectId, { suggestionId });
  expect(replay.replayed).toBe(true);
  expect(replay.document_result.version.version_id).toBe(saved.document_result.version.version_id);
  expect(writes).toHaveLength(5);
  expect(writes[3]).toEqual(writes[2]);
  expect(writes[4]).toEqual(writes[2]);
  await expect(officeEditor(page)).toHaveText("Accepted retry wording");
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, objectId)).toHaveLength(2);
});

test("Office closing or changing context suppresses late real suggestion bodies", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic suggestion late response", "Stable selected text");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const created = await createSuggestion(page, objectId, "selected", "Late proposal secret");
  const suggestionId = created.suggestion.suggestion_id;
  await refreshSuggestions(page, objectId);
  await observeStaleSuggestion(page, "Late proposal secret");
  const closed = await holdSuggestionRead(page, objectId, suggestionId);
  try {
    await suggestionCard(page, suggestionId).locator('[data-suggestion-action="open"]').click();
    await closed.ready;
    await page.locator("#suggestions-close").click();
    await closed.complete();
    await expect(page.locator("#suggestions-panel")).toBeHidden();
    expect(await page.evaluate(() => window.staleOfficeSuggestion)).toBe(false);
  } finally { closed.release(); }
  await openSuggestions(page, objectId);
  const changed = await holdSuggestionRead(page, objectId, suggestionId);
  try {
    await suggestionCard(page, suggestionId).locator('[data-suggestion-action="open"]').click();
    await changed.ready;
    const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    await page.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect((await pending).status()).toBe(200);
    await changed.complete();
    await expect(page.locator("#suggestions-list")).toHaveText("");
    await expect(page.locator("#office-editor")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficeSuggestion)).toBe(false);
  } finally { changed.release(); }
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
});

test("Office suggestion drafts require clean saved text and cancelled discard preserves the local replacement", async ({ page }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic suggestion draft boundaries", { text: "Saved proposal source" });
  await expect(page.locator("#suggestions-toggle")).toBeDisabled();
  const first = await saveOffice(page);
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  await officeEditor(page).fill("Dirty source has no exact anchor");
  await expect(page.locator("#suggestion-new")).toBeDisabled();
  await officeEditor(page).press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled();
  const writes = collectSuggestionWrites(page);
  await prepareSuggestion(page, "proposal", "Local replacement draft");
  await page.locator("#suggestion-confirm-cancel").click();
  await page.locator("#document-close").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(page.locator("#suggestion-replacement")).toHaveValue("Local replacement draft");
  await expect(officeEditor(page)).toHaveText("Saved proposal source");
  await page.locator("#suggestion-prepare").click();
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#suggestion-confirm-dialog")).toBeHidden();
  await expect(page.locator("#suggestion-replacement")).toHaveValue("");
  await expect(page.locator("#document-workspace")).toBeHidden();
  expect(writes).toHaveLength(0);
  expect((await readSuggestions(page, objectId)).suggestions).toEqual([]);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});

featureTest("Office suggestion acceptance rechecks the write feature after explicit preparation", async ({ page, restoreOfficeFeatures }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic gated suggestion", "Feature protected text");
  const objectId = first.document.object_id;
  await openSuggestions(page, objectId);
  const created = await createSuggestion(page, objectId, "protected", "proposed");
  const suggestionId = created.suggestion.suggestion_id;
  await openSuggestion(page, objectId, suggestionId);
  await prepareSuggestionDecision(page, suggestionId, "accept");
  const previous = await officeFeatures(page);
  restoreOfficeFeatures(previous);
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  await confirmSuggestion(page, objectId, { suggestionId, status: 403 });
  await expect(page.locator("#document-workspace")).toBeHidden();
  await expect(page.locator("#suggestions-list")).toHaveText("");
  await expect(page.locator("#suggestion-replacement")).toHaveValue("");
  expect((await readSuggestion(page, objectId, suggestionId)).suggestion.status).toBe("open");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
});
