import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_HEADERS, OFFICE_PATH, OFFICE_READER_HEADERS, OFFICE_READER_ID,
  captureOfficeResponse, createOfficeDocument, holdOfficeRead, newOfficeDraft, officeContent, officeContentPath,
  officeEditor, officeFeatures, officeVersions, openOffice, openOfficeDocument, saveOffice, setOfficeAcl, setOfficeFeatures,
} from "./office-support.mjs";
import { createReview, openComments, prepareComment, readReview, reviewPath } from "./office-review-support.mjs";
import { createSuggestion, openSuggestions, readSuggestion, readSuggestions } from "./office-suggestion-support.mjs";
import {
  collectReuseRequests, createReusableSource, expectReuseDraft, observeReuseDraft,
  openReuse, openReuseHistory, submitReuse,
} from "./office-reuse-support.mjs";

const featureTest = test.extend({
  restoreOfficeFeatures: [async ({ request }, use) => {
    let previous = null;
    try { await use((features) => { previous = { ...features }; }); }
    finally { if (previous !== null) await setOfficeFeatures({ request }, previous); }
  }, { timeout: 20_000 }],
});

const writes = (requests) => requests.filter((request) => request.method === "POST");

test("Office reuses exact historical formatting as an independent confirmed document without copying access or discussions", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await createReusableSource(page);
  const sourceId = first.document.object_id;
  await openOffice(page);
  await openOfficeDocument(page, sourceId);
  await openComments(page, sourceId);
  const review = await createReview(page, sourceId, "Discussion belongs only to the source");
  await page.locator("#comments-close").click();
  await openSuggestions(page, sourceId);
  const suggestion = await createSuggestion(page, sourceId, "Original selected wording", "Unaccepted source proposal");
  await page.locator("#suggestions-close").click();
  await setOfficeAcl(page, sourceId);
  await page.locator("#document-title").fill("Newer source title must stay independent");
  await officeEditor(page).fill("Newer source content is not the selected version");
  const current = await saveOffice(page, { objectId: sourceId });
  await openReuseHistory(page, first);
  const requests = collectReuseRequests(page);
  const title = '<img src="https://reuse.invalid/title" onerror="window.reuseExecuted=true"> Independent 😀';
  await openReuse(page, first, title);
  expect(requests).toHaveLength(0);
  const prepared = await submitReuse(page, first);
  expect(prepared.listing.can_create).toBe(true);
  await expectReuseDraft(page, title);
  await expect(officeEditor(page).locator("h2")).toHaveText("Saved source heading");
  await expect(officeEditor(page).locator("strong em, em strong")).toHaveText("Original selected wording");
  await expect(officeEditor(page).locator("table")).toContainText("Keep original marks");
  await expect(officeEditor(page).locator("table u")).toHaveCount(2);
  await expect(page.locator("#comments-list, #suggestions-list")).toHaveText(["", ""]);
  expect(writes(requests)).toHaveLength(0);
  expect(await officeVersions(page, sourceId)).toHaveLength(2);
  const created = await saveOffice(page);
  expect(created.document.object_id).not.toBe(sourceId);
  expect(created.version.previous_version_id).toBeNull();
  expect(created.content).toEqual(first.content);
  expect(created.version.title).toBe(title);
  expect(created.can_write).toBe(true);
  expect(writes(requests)).toHaveLength(1);
  expect(writes(requests)[0].path).toBe(OFFICE_PATH);
  expect(writes(requests)[0].body.human_confirmation).toBe(true);
  expect(await officeVersions(page, created.document.object_id)).toHaveLength(1);
  expect((await officeContent(page, sourceId)).version.version_id).toBe(current.version.version_id);
  expect((await officeContent(page, sourceId, { versionId: first.version.version_id })).content).toEqual(first.content);
  expect((await readReview(page, sourceId, review.thread.thread_id)).events).toHaveLength(1);
  expect((await readSuggestion(page, sourceId, suggestion.suggestion.suggestion_id)).suggestion.status).toBe("open");
  const comments = await page.request.get(`${BASE_URL}${reviewPath(created.document.object_id)}`, { headers: OFFICE_HEADERS });
  expect(comments.status()).toBe(200);
  expect((await comments.json()).threads).toEqual([]);
  expect((await readSuggestions(page, created.document.object_id)).suggestions).toEqual([]);
  const sourceReader = await page.request.get(`${BASE_URL}${officeContentPath(sourceId)}`, { headers: OFFICE_READER_HEADERS });
  expect(sourceReader.status()).toBe(200);
  const unrelatedCopy = await page.request.get(`${BASE_URL}${officeContentPath(created.document.object_id)}`, { headers: OFFICE_READER_HEADERS });
  expect(unrelatedCopy.status()).toBe(404);
  expect((await unrelatedCopy.json()).detail).toBe("Document not found");
  await page.locator("#document-close").click();
  expect((await openOfficeDocument(page, created.document.object_id)).content).toEqual(first.content);
  await expect(page.locator("#document-title")).toHaveValue(title);
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
  expect(await page.evaluate(() => window.reuseExecuted)).toBeUndefined();
  verifyBrowser();
});

test("Office source read access suffices for a create-capable actor while ordinary readers cannot start a copy", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic read-only reuse source", "Read access is sufficient to reuse");
  await setOfficeAcl(page, first.document.object_id);
  const list = await openOffice(page, { userId: OFFICE_READER_ID, roleIds: "office-editor" });
  expect(list.can_create).toBe(true);
  const readOnly = await openOfficeDocument(page, first.document.object_id);
  expect(readOnly.can_write).toBe(false);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  const requests = collectReuseRequests(page);
  await openReuse(page, first, "Independent reader-created document");
  expect((await submitReuse(page, first)).source.can_write).toBe(false);
  await expectReuseDraft(page, "Independent reader-created document");
  expect(writes(requests)).toHaveLength(0);
  const created = await saveOffice(page);
  expect(created.document.object_id).not.toBe(first.document.object_id);
  expect(created.can_write).toBe(true);
  expect(created.version.created_by).toBe(OFFICE_READER_ID);
  const creatorHeaders = { ...OFFICE_READER_HEADERS, "X-Role-Ids": "office-editor" };
  expect((await officeContent(page, created.document.object_id, { headers: creatorHeaders })).content).toEqual(first.content);
  const formerOwner = await page.request.get(`${BASE_URL}${officeContentPath(created.document.object_id)}`, { headers: OFFICE_HEADERS });
  expect(formerOwner.status()).toBe(404);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  const readerList = await openOffice(page, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  expect(readerList.can_create).toBe(false);
  await openOfficeDocument(page, first.document.object_id);
  await expect(page.locator("#document-reuse")).toBeDisabled();
  await expect(page.locator("#reuse-dialog")).toBeHidden();
});

test("Office freshly revoked source access denies reuse and clears protected source content", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic revoked reuse", "Protected reuse source");
  const requests = collectReuseRequests(page);
  await openReuse(page, first, "Must never become a draft");
  await setOfficeAcl(page, first.document.object_id, { creator: true, status: "revoked" });
  try {
    await submitReuse(page, first, { status: 404 });
    await expect(page.locator("#reuse-dialog")).toBeHidden();
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator("#document-title")).toHaveValue("");
    await expect(page.locator("#documents-status")).toContainText("nicht mehr freigegeben");
    expect(writes(requests)).toHaveLength(0);
  } finally { await setOfficeAcl(page, first.document.object_id, { creator: true }); }
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

featureTest("Office rechecks create permission after discard confirmation and again at the eventual independent save", async ({ page, restoreOfficeFeatures }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic create-gated reuse", "Saved capability source");
  await officeEditor(page).fill("Existing unsaved work must survive denied create permission");
  const previous = await officeFeatures(page);
  restoreOfficeFeatures(previous);
  const requests = collectReuseRequests(page);
  await openReuse(page, first, "Denied independent draft");
  const preparing = submitReuse(page, first);
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  await page.locator("#discard-confirm").click();
  expect((await preparing).listing.can_create).toBe(false);
  await expect(page.locator("#reuse-status")).toContainText("kein neues Dokument anlegen");
  await expect(officeEditor(page)).toHaveText("Existing unsaved work must survive denied create permission");
  expect(writes(requests)).toHaveLength(0);
  await setOfficeFeatures(page, previous);
  await openOffice(page);
  await openOfficeDocument(page, first.document.object_id);
  await openReuse(page, first, "Prepared while creation was allowed");
  await submitReuse(page, first);
  await expectReuseDraft(page, "Prepared while creation was allowed");
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  await saveOffice(page, { status: 403 });
  await expect(page.locator("#office-editor")).toHaveText("");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
});

test("Office canceled discard and failed exact-version reads preserve the dirty draft until a successful reuse", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic retry reuse", "Persisted reusable wording");
  await officeEditor(page).fill("Unsaved wording must not be silently reused or lost");
  await page.locator("#document-title").fill("Unsaved source title");
  const requests = collectReuseRequests(page);
  await openReuse(page, first, "Fresh independent retry");
  await page.locator("#reuse-submit").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(page.locator("#reuse-dialog")).toBeVisible();
  await expect(officeEditor(page)).toHaveText("Unsaved wording must not be silently reused or lost");
  await expect(page.locator("#document-title")).toHaveValue("Unsaved source title");
  expect(requests).toHaveLength(0);
  const failing = submitReuse(page, first, { status: 503, extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await failing;
  await expect(page.locator("#reuse-status")).toContainText("Bitte versuchen Sie es erneut");
  await expect(officeEditor(page)).toHaveText("Unsaved wording must not be silently reused or lost");
  await expect(page.locator("#document-title")).toHaveValue("Unsaved source title");
  const retried = submitReuse(page, first);
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await retried;
  await expectReuseDraft(page, "Fresh independent retry");
  await expect(officeEditor(page)).toHaveText("Persisted reusable wording");
  expect(writes(requests)).toHaveLength(0);
  const reads = requests.filter((request) => request.path === officeContentPath(first.document.object_id));
  expect(reads).toHaveLength(2);
  expect(reads.every((request) => request.versionId === first.version.version_id)).toBe(true);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office closing reuse or changing context suppresses late saved-version responses", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic late reuse", "Saved reuse source remains unchanged");
  const title = "Late draft must never appear";
  const requests = collectReuseRequests(page);
  await observeReuseDraft(page, title);
  await openReuse(page, first, title);
  const closed = await holdOfficeRead(page, first.document.object_id, { versionId: first.version.version_id });
  try {
    await page.locator("#reuse-submit").click();
    await closed.ready;
    await page.locator("#reuse-close").click();
    await closed.complete();
    await expect(page.locator("#reuse-dialog")).toBeHidden();
    await expect(page.locator("#document-title")).toHaveValue(first.version.title);
    await expect(page.locator("#document-save")).toBeDisabled();
    expect(await page.evaluate(() => window.staleReuseDraft)).toBe(false);
  } finally { closed.release(); }
  await openReuse(page, first, title);
  const changed = await holdOfficeRead(page, first.document.object_id, { versionId: first.version.version_id });
  try {
    await page.locator("#reuse-submit").click();
    await changed.ready;
    const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    await page.evaluate(() => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect((await pending).status()).toBe(200);
    await changed.complete();
    await expect(page.locator("#reuse-dialog")).toBeHidden();
    await expect(page.locator("#office-editor")).toHaveText("");
    expect(await page.evaluate(() => window.staleReuseDraft)).toBe(false);
    expect(writes(requests)).toHaveLength(0);
  } finally { changed.release(); }
});

test("Office blocks reuse of new busy and uncertain drafts and retries a lost independent-create response exactly once", async ({ page }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic reuse states", { text: "Saved reuse state source" });
  await expect(page.locator("#document-reuse")).toBeDisabled();
  const first = await saveOffice(page);
  await officeEditor(page).fill("Updated saved reuse state source");
  let releaseSave;
  let startedSave;
  const saveGate = new Promise((resolve) => { releaseSave = resolve; });
  const saving = new Promise((resolve) => { startedSave = resolve; });
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  const failedSave = await captureOfficeResponse(page, (url) => url.pathname === path, { method: "POST", extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  // Register the gate last: fallback reaches the real upstream capture only
  // after the pending state has been observed on an existing saved object.
  await page.route((url) => url.pathname === path, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    startedSave();
    await saveGate;
    await route.fallback();
  }, { times: 1 });
  try {
    await page.locator("#document-save").click();
    await page.locator("#save-confirm").check();
    const delivered = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
    await page.locator("#save-submit").click();
    await saving;
    await expect(page.locator("#document-reuse")).toBeDisabled();
    releaseSave();
    const response = await delivered;
    expect(response.status()).toBe(503);
    expect(response.headers()["cache-control"]).toContain("no-store");
    const upstream = await failedSave.received;
    expect(upstream.status).toBe(503);
    expect(upstream.json.detail).toBe("Office storage unavailable");
    await expect(page.locator("#save-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expect(page.locator("#document-reuse")).toBeDisabled();
  } finally { releaseSave(); }
  const current = await saveOffice(page, { objectId: first.document.object_id });
  await openReuse(page, current, "Independent create with lost acknowledgment");
  await submitReuse(page, current);
  await expectReuseDraft(page, "Independent create with lost acknowledgment");
  const requests = collectReuseRequests(page);
  let started;
  let release;
  let committed;
  const ready = new Promise((resolve) => { started = resolve; });
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route((url) => url.pathname === OFFICE_PATH, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    started();
    await gate;
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    expect(response.status()).toBe(200);
    committed = await response.json();
    await route.abort("connectionreset");
  }, { times: 1 });
  try {
    await page.locator("#document-save").click();
    await expect(page.locator("#save-submit")).toBeDisabled();
    await page.locator("#save-confirm").check();
    await page.locator("#save-submit").click();
    await ready;
    await expect(page.locator("#document-reuse")).toBeDisabled();
    release();
    await expect(page.locator("#save-dialog")).toBeHidden();
    await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
    await expect(page.locator("#document-reuse")).toBeDisabled();
    await expect(officeEditor(page)).toHaveText("Updated saved reuse state source");
    const replay = await saveOffice(page);
    expect(replay.replayed).toBe(true);
    expect(replay.document.object_id).toBe(committed.document.object_id);
    expect(replay.version.version_id).toBe(committed.version.version_id);
    expect(replay.document.object_id).not.toBe(first.document.object_id);
    const attempts = writes(requests);
    expect(attempts).toHaveLength(2);
    expect(attempts[1]).toEqual(attempts[0]);
    expect(await officeVersions(page, replay.document.object_id)).toHaveLength(1);
    expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  } finally { release(); }
});

test("Office reuse validates its title and preserves an unconfirmed discussion until discard is explicitly accepted", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, `Synthetic ${"😀".repeat(86)} saved title`, "Review draft source");
  await openComments(page, first.document.object_id);
  await prepareComment(page, "Unconfirmed discussion must survive cancellation");
  await page.locator("#comment-confirm-cancel").click();
  const requests = collectReuseRequests(page);
  await openReuse(page, first);
  const defaultTitle = await page.locator("#reuse-title").inputValue();
  expect(defaultTitle).toContain("Kopie von");
  expect(defaultTitle.length).toBeLessThanOrEqual(200);
  expect(defaultTitle.isWellFormed()).toBe(true);
  await page.locator("#reuse-title").fill("");
  await expect(page.locator("#reuse-submit")).toBeDisabled();
  expect(await page.locator("#reuse-title").evaluate((input) => input.checkValidity())).toBe(false);
  expect(requests).toHaveLength(0);
  await page.locator("#reuse-title").fill("Independent after explicit discussion discard");
  await page.locator("#reuse-submit").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(page.locator("#comment-body")).toHaveValue("Unconfirmed discussion must survive cancellation");
  expect(requests).toHaveLength(0);
  const prepared = submitReuse(page, first);
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await prepared;
  await expectReuseDraft(page, "Independent after explicit discussion discard");
  await expect(page.locator("#comment-body")).toHaveValue("");
  expect(writes(requests)).toHaveLength(0);
  const review = await page.request.get(`${BASE_URL}${reviewPath(first.document.object_id)}`, { headers: OFFICE_HEADERS });
  expect(review.status()).toBe(200);
  expect((await review.json()).threads).toEqual([]);
});
