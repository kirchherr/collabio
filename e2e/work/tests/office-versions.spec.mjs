import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_HEADERS, OFFICE_PATH, OFFICE_READER_ID, captureOfficeResponse, createOfficeVersionPair, holdOfficeRead,
  loadOfficeComparison, newOfficeDraft, observeStaleOfficeContent, officeContent,
  officeContentPath, officeEditor, officeFeatures, officeVersions, openOffice,
  openOfficeComparison, openOfficeDocument, saveOffice, setOfficeAcl, setOfficeFeatures,
} from "./office-support.mjs";

const featureTest = test.extend({
  restoreOfficeFeatures: [async ({ request }, use) => {
    let previous = null;
    try { await use((features) => { previous = { ...features }; }); }
    finally { if (previous !== null) await setOfficeFeatures({ request }, previous); }
  }, { timeout: 20_000 }],
});

function collectWrites(page) {
  const writes = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.startsWith(OFFICE_PATH)) writes.push(request.postDataJSON());
  });
  return writes;
}

async function comparePair(page, pair) {
  await openOfficeComparison(page);
  await expect(page.locator("#compare-left")).toHaveValue(pair.first.version.version_id);
  await expect(page.locator("#compare-right")).toHaveValue(pair.second.version.version_id);
  await loadOfficeComparison(page, pair.objectId, pair.first.version.version_id, pair.second.version.version_id);
}

async function expectAdoptedDraft(page, title, text) {
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(page.locator("#document-title")).toHaveValue(title);
  await expect(officeEditor(page)).toHaveText(text);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await expect(page.locator("#document-notice")).toContainText("ungespeicherten Entwurf übernommen");
  await expect(page.locator("#document-save")).toBeEnabled();
}

async function observeComparisonText(page, text) {
  await page.evaluate((unexpectedText) => {
    window.staleOfficeComparison = false;
    new MutationObserver(() => {
      window.staleOfficeComparison ||= document.querySelector("#compare-results").textContent.includes(unexpectedText);
    }).observe(document.querySelector("#compare-results"), { subtree: true, childList: true, characterData: true });
  }, text);
}

async function captureRevokedTakeoverReads(page, objectId) {
  const matches = (url) => url.pathname === officeContentPath(objectId);
  const failedRequests = new Map();
  const failed = (request) => { if (matches(new URL(request.url()))) failedRequests.set(request, request.failure()?.errorText); };
  page.on("requestfailed", failed);
  const replies = [];
  const jobs = [];
  let complete;
  let bothReady;
  let failReady;
  const received = new Promise((resolve) => { complete = resolve; });
  const ready = new Promise((resolve, reject) => { bothReady = resolve; failReady = reject; });
  const handler = (route) => {
    const job = (async () => {
      const request = route.request();
      expect(request.method()).toBe("GET");
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      const body = await response.body();
      const result = { status: response.status(), headers: response.headers(), json: JSON.parse(body.toString("utf8")) };
      replies.push(result);
      // Read both actual upstream replies while the ACL is still revoked. The
      // first delivered denial may then abort its parallel browser request.
      if (replies.length === 2) bothReady();
      await ready;
      try { await route.fulfill({ response, body }); }
      catch (error) {
        if (!String(error).includes("Route is already handled!")) throw error;
        await expect.poll(() => failedRequests.get(request), { message: "The exact sibling request must have been aborted by the browser" }).toBe("net::ERR_ABORTED");
        return;
      }
      complete(result);
    })().catch((error) => { failReady(error); throw error; });
    jobs.push(job);
    return job;
  };
  await page.route(matches, handler, { times: 2 });
  return { received, replies, async dispose() {
    try {
      await page.unroute(matches, handler);
      if (jobs.length > 0 && replies.length < 2) failReady(new Error("Both revoked takeover reads must reach the capture barrier"));
      const settled = await Promise.allSettled(jobs);
      for (const result of settled) if (result.status === "rejected") throw result.reason;
    } finally { page.off("requestfailed", failed); }
  } };
}

test("Office compares exact saved text, formatting, titles and tables without writing, including equal versions", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic comparison earlier", { text: "Earlier decision wording" });
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTable");
  await page.keyboard.type("Earlier table owner");
  const first = await saveOffice(page);
  await page.locator("#document-title").fill("Synthetic comparison current");
  await officeEditor(page).locator("p").first().click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Shift+End");
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.type("Current decision wording");
  await officeEditor(page).locator("th").first().click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Shift+End");
  await page.keyboard.type("Current table owner");
  const second = await saveOffice(page, { objectId: first.document.object_id });
  const writes = collectWrites(page);
  const pair = { first, second, objectId: first.document.object_id };
  await comparePair(page, pair);
  const results = page.locator("#compare-results");
  await expect(results).toContainText("Earlier decision wording");
  await expect(results).toContainText("Current decision wording");
  await expect(results).toContainText("Earlier table owner");
  await expect(results).toContainText("Current table owner");
  await expect(results).toContainText("Fett");
  await expect(page.locator("#compare-dialog")).toContainText(first.version.title);
  await expect(page.locator("#compare-dialog")).toContainText(second.version.title);
  await expect(page.locator("#compare-restore")).toBeEnabled();
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
  expect((await officeContent(page, pair.objectId, { versionId: first.version.version_id })).content).toEqual(first.content);
  await loadOfficeComparison(page, pair.objectId, second.version.version_id, second.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("0 geändert");
  await expect(page.locator("#compare-restore")).toBeDisabled();
  expect(writes).toHaveLength(0);
  verifyBrowser();
});

test("Office historical takeover creates only a draft and explicit save extends the freshly loaded current head", async ({ page, context }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic restore lineage");
  await comparePair(page, pair);
  const other = await context.newPage();
  await openOffice(other);
  await openOfficeDocument(other, pair.objectId);
  await officeEditor(other).fill("A newer head before historical takeover");
  const newest = await saveOffice(other, { objectId: pair.objectId });
  const writes = collectWrites(page);
  await page.locator("#compare-restore").click();
  await expectAdoptedDraft(page, pair.first.version.title, "Earlier saved wording");
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(3);
  expect((await officeContent(page, pair.objectId)).version.version_id).toBe(newest.version.version_id);
  const restored = await saveOffice(page, { objectId: pair.objectId });
  expect(writes).toHaveLength(1);
  expect(writes[0].expected_current_version_id).toBe(newest.version.version_id);
  expect(writes[0].human_confirmation).toBe(true);
  expect(restored.version.previous_version_id).toBe(newest.version.version_id);
  expect(restored.version.title).toBe(pair.first.version.title);
  expect(restored.content).toEqual(pair.first.content);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(4);
  expect((await officeContent(page, pair.objectId, { versionId: pair.second.version.version_id })).content).toEqual(pair.second.content);
});

test("Office compares a bounded real history window and takes over its historical entry without writing", async ({ page }) => {
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic bounded history", { text: "Earlier saved wording" });
  const first = await saveOffice(page);
  const objectId = first.document.object_id;
  let previous = first;
  // Genuine committed predecessors naturally extend beyond the UI's 50-row page.
  for (let number = 2; number <= 50; number += 1) {
    const text = number === 50 ? "Current saved wording" : `Intermediate saved wording ${number}`;
    const response = await page.request.post(`${BASE_URL}${OFFICE_PATH}/${objectId}/versions`, {
      headers: OFFICE_HEADERS,
      data: {
        title: "Synthetic bounded history", document: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] },
        expected_current_version_id: previous.version.version_id,
        mutation_reference: `bounded-history-${objectId}-${number}`, human_confirmation: true,
      },
    });
    expect(response.status()).toBe(200);
    previous = await response.json();
  }
  const pair = { first, second: previous, objectId };
  await page.locator("#document-reload").click();
  await expect(officeEditor(page)).toHaveText("Current saved wording");
  await officeEditor(page).fill("Third saved wording outside the old pair");
  const third = await saveOffice(page, { objectId: pair.objectId });
  const writes = collectWrites(page);
  await openOfficeComparison(page);
  await expect(page.locator("#compare-left")).toHaveValue(pair.second.version.version_id);
  await expect(page.locator("#compare-right")).toHaveValue(third.version.version_id);
  await expect(page.locator("#compare-left option:checked")).toHaveText(/1 Fassung zuvor/);
  await expect(page.locator("#compare-right option:checked")).toHaveText(/Aktuelle Fassung/);
  await loadOfficeComparison(page, pair.objectId, pair.second.version.version_id, third.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("ältere Fassungen sind nicht geladen");
  await expect(page.locator("#compare-results")).toContainText("Current saved wording");
  await expect(page.locator("#compare-results")).toContainText("Third saved wording outside the old pair");
  await page.locator("#compare-close").click();
  await expect(page.locator("#history-status")).toContainText("ältere Fassungen sind nicht geladen");
  await page.locator(`[data-version-id="${pair.second.version.version_id}"]`).click();
  await expect(officeEditor(page)).toHaveText("Current saved wording");
  await expect(page.locator("#document-restore")).toBeVisible();
  await page.locator("#document-restore").click();
  await expectAdoptedDraft(page, pair.second.version.title, "Current saved wording");
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(51);
});

test("Office restored draft survives a later competing save with a real CAS conflict", async ({ page, context }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic restore conflict");
  await comparePair(page, pair);
  await page.locator("#compare-restore").click();
  await expectAdoptedDraft(page, pair.first.version.title, "Earlier saved wording");
  const other = await context.newPage();
  await openOffice(other);
  await openOfficeDocument(other, pair.objectId);
  await officeEditor(other).fill("Concurrent winner after takeover");
  const winner = await saveOffice(other, { objectId: pair.objectId });
  const captured = await captureOfficeResponse(page, (url) => url.pathname === `${OFFICE_PATH}/${pair.objectId}/versions`, { method: "POST" });
  await page.locator("#document-save").click();
  await expect(page.locator("#save-dialog")).toBeVisible();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-confirm").check();
  const browserResponse = page.waitForResponse((response) => new URL(response.url()).pathname === `${OFFICE_PATH}/${pair.objectId}/versions` && response.request().method() === "POST");
  await page.locator("#save-submit").click();
  const delivered = await browserResponse;
  expect(delivered.status()).toBe(409);
  expect(delivered.headers()["cache-control"]).toContain("no-store");
  const conflict = await captured.received;
  expect(conflict.status).toBe(409);
  expect(conflict.headers["cache-control"]).toContain("no-store");
  expect(conflict.json.detail).toBe("The document has a newer or conflicting saved version");
  await expect(page.locator("#save-dialog")).toBeHidden();
  await expect(officeEditor(page)).toHaveText("Earlier saved wording");
  await expect(page.locator("#document-title")).toHaveValue(pair.first.version.title);
  await expect(page.locator("#document-notice")).toContainText("Ihr Entwurf wurde nicht überschrieben");
  expect((await officeContent(page, pair.objectId)).version.version_id).toBe(winner.version.version_id);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(3);
});

test("Office reader compares real historical versions with writes disabled and cannot take over a version", async ({ page, context }) => {
  await openOffice(page);
  const literal = '<img src="https://invalid.example/compare" onerror="window.compareAttack=true"><script>window.compareAttack=true</script>';
  const pair = await createOfficeVersionPair(page, "Synthetic reader comparison", literal, "Current ordinary reader text");
  await setOfficeAcl(page, pair.objectId);
  const reader = await context.newPage();
  const verifyBrowser = monitorPage(reader, { baseUrls: [BLOCKED_BASE_URL] });
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, pair.objectId);
  const writes = collectWrites(reader);
  await comparePair(reader, pair);
  await expect(reader.locator("#compare-results")).toContainText(literal);
  await expect(reader.locator("#compare-results")).toContainText("Current ordinary reader text");
  await expect(reader.locator("#compare-results img, #compare-results script")).toHaveCount(0);
  expect(await reader.evaluate(() => window.compareAttack)).toBeUndefined();
  await expect(reader.locator("#compare-restore")).toBeDisabled();
  await reader.locator("#compare-close").click();
  await reader.locator(`[data-version-id="${pair.first.version.version_id}"]`).click();
  await expect(officeEditor(reader)).toHaveText(literal);
  await expect(reader.locator("#document-restore")).toBeHidden();
  await expect(reader.locator("#document-save")).toBeDisabled();
  expect(writes).toHaveLength(0);
  verifyBrowser();
});

test("Office current ACL revocation during comparison denies takeover and clears previously visible content", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic comparison revocation");
  await comparePair(page, pair);
  const writes = collectWrites(page);
  await setOfficeAcl(page, pair.objectId, { creator: true, status: "revoked" });
  const captured = await captureRevokedTakeoverReads(page, pair.objectId);
  try {
    // Both fresh content reads can independently deny access and abort the other.
    // Buffer their genuine upstream replies before the UI clears protected state.
    const denied = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(pair.objectId) && response.status() === 404);
    await page.locator("#compare-restore").click();
    expect((await denied).headers()["cache-control"]).toContain("no-store");
    const upstream = await captured.received;
    expect(upstream.status).toBe(404);
    expect(upstream.headers["cache-control"]).toContain("no-store");
    expect(upstream.json.detail).toBe("Document not found");
    await expect(page.locator("#compare-dialog")).toBeHidden();
    await expect(page.locator("#compare-results")).toHaveText("");
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator("#document-title")).toHaveValue("");
    await expect(page.locator("#documents-status")).toContainText("nicht mehr freigegeben");
    expect(writes).toHaveLength(0);
  } finally {
    try { await captured.dispose(); }
    finally { await setOfficeAcl(page, pair.objectId, { creator: true }); }
  }
  expect(captured.replies).toHaveLength(2);
  for (const reply of captured.replies) {
    expect(reply.status).toBe(404);
    expect(reply.headers["cache-control"]).toContain("no-store");
    expect(reply.json.detail).toBe("Document not found");
  }
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
});

featureTest("Office takeover rechecks the current write feature and clears the workspace when it closes", async ({ page, restoreOfficeFeatures }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic restore feature");
  await comparePair(page, pair);
  const previous = await officeFeatures(page);
  restoreOfficeFeatures(previous);
  await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
  const writes = collectWrites(page);
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(page.locator("#compare-results")).toHaveText("");
  await expect(page.locator("#office-editor")).toHaveText("");
  await expect(page.locator("#documents-status")).toContainText("nicht mehr freigegeben");
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
  const current = await officeContent(page, pair.objectId);
  expect(current.version.version_id).toBe(pair.second.version.version_id);
  expect(current.can_write).toBe(false);
});

test("Office canceling historical takeover preserves the unsaved draft and immutable history", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic canceled takeover");
  await officeEditor(page).fill("Keep my unsaved current draft");
  await page.locator("#document-title").fill("Unsaved title remains mine");
  await comparePair(page, pair);
  const writes = collectWrites(page);
  await page.locator("#compare-restore").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeHidden();
  await expect(officeEditor(page)).toHaveText("Keep my unsaved current draft");
  await expect(page.locator("#document-title")).toHaveValue("Unsaved title remains mine");
  if (await page.locator("#compare-dialog").isVisible()) await page.locator("#compare-close").click();
  await expect(page.locator("#document-save")).toBeEnabled();
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
});

test("Office comparison storage failure clears its results and retries exact source versions safely", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic comparison retry");
  await comparePair(page, pair);
  const writes = collectWrites(page);
  const captured = await captureOfficeResponse(page,
    (url) => url.pathname === officeContentPath(pair.objectId) && url.searchParams.get("version_id") === pair.first.version.version_id,
    { extraHeaders: { "X-Work-E2E-Fail-Storage": "1" } });
  const failed = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(pair.objectId) && response.status() === 503);
  await page.locator("#compare-load").click();
  const browserResponse = await failed;
  const upstream = await captured.received;
  expect(browserResponse.status()).toBe(503);
  expect(browserResponse.headers()["cache-control"]).toContain("no-store");
  expect(upstream.status).toBe(503);
  expect(upstream.headers["cache-control"]).toContain("no-store");
  expect(upstream.json.detail).toBe("Office storage unavailable");
  await expect(page.locator("#compare-dialog")).toBeVisible();
  await expect(page.locator("#compare-results")).toHaveText("");
  await expect(page.locator("#compare-status")).toContainText("Vergleich konnte nicht geladen werden");
  await expect(page.locator("#compare-restore")).toBeDisabled();
  await loadOfficeComparison(page, pair.objectId, pair.first.version.version_id, pair.second.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("Earlier saved wording");
  await expect(page.locator("#compare-results")).toContainText("Current saved wording");
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
});

test("Office closes a pending comparison without rendering its late real response", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic closed comparison");
  await openOfficeComparison(page);
  await observeComparisonText(page, "Earlier saved wording");
  const held = await holdOfficeRead(page, pair.objectId, { versionId: pair.first.version.version_id });
  try {
    await page.locator("#compare-load").click();
    await held.ready;
    await page.locator("#compare-close").click();
    await expect(page.locator("#compare-dialog")).toBeHidden();
    await held.complete();
    await expect(page.locator("#compare-results")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficeComparison)).toBe(false);
    await expect(officeEditor(page)).toHaveText("Current saved wording");
  } finally { held.release(); }
});

test("Office changing the selected versions discards the previous pending comparison", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic selection race");
  await openOfficeComparison(page);
  await observeComparisonText(page, "Earlier saved wording");
  const held = await holdOfficeRead(page, pair.objectId, { versionId: pair.first.version.version_id });
  try {
    await page.locator("#compare-load").click();
    await held.ready;
    await page.locator("#compare-left").selectOption(pair.second.version.version_id);
    await expect(page.locator("#compare-results")).toHaveText("");
    await held.complete();
    await expect(page.locator("#compare-results")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficeComparison)).toBe(false);
    await loadOfficeComparison(page, pair.objectId, pair.second.version.version_id, pair.second.version.version_id);
    await expect(page.locator("#compare-summary")).toContainText("0 geändert");
    await expect(page.locator("#compare-restore")).toBeDisabled();
  } finally { held.release(); }
});

test("Office context change discards a pending comparison and clears the previous principal's content", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic comparison context");
  await openOfficeComparison(page);
  await observeComparisonText(page, "Earlier saved wording");
  const held = await holdOfficeRead(page, pair.objectId, { versionId: pair.first.version.version_id });
  try {
    await page.locator("#compare-load").click();
    await held.ready;
    const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
    // The native modal makes background controls inert; submit the actual context form event.
    await page.evaluate((objectId) => {
      document.querySelector("#user-id").value = "work-assignee-e2e";
      document.querySelector("#role-ids").value = "office-reader";
      document.querySelector("#readable-object-ids").value = objectId;
      document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }, pair.objectId);
    expect((await changed).status()).toBe(200);
    await expect(page.locator("#compare-dialog")).toBeHidden();
    await expect(page.locator("#document-workspace")).toBeHidden();
    await held.complete();
    await expect(page.locator("#compare-results")).toHaveText("");
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator(`[data-document-id="${pair.objectId}"]`)).toHaveCount(0);
    expect(await page.evaluate(() => window.staleOfficeComparison)).toBe(false);
  } finally { held.release(); }
});

test("Office closing comparison during fresh takeover reads prevents a late historical draft", async ({ page }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic takeover close race");
  await comparePair(page, pair);
  await observeStaleOfficeContent(page, "Earlier saved wording");
  const writes = collectWrites(page);
  const held = await holdOfficeRead(page, pair.objectId, { versionId: pair.first.version.version_id });
  try {
    await page.locator("#compare-restore").click();
    await held.ready;
    await page.locator("#compare-close").click();
    await expect(page.locator("#compare-dialog")).toBeHidden();
    await held.complete();
    await expect(officeEditor(page)).toHaveText("Current saved wording");
    await expect(page.locator("#document-title")).toHaveValue(pair.second.version.title);
    await expect(page.locator("#document-save")).toBeDisabled();
    expect(await page.evaluate(() => window.staleOfficeContent)).toBe(false);
    expect(writes).toHaveLength(0);
    expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
  } finally { held.release(); }
});
