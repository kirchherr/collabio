import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_EDITOR_ID, OFFICE_HEADERS, OFFICE_PATH, OFFICE_READER_HEADERS, OFFICE_READER_ID,
  createOfficeDocument, holdOfficeRead, newOfficeDraft, observeStaleOfficeContent,
  officeContent, officeContentPath, officeEditor, officeFeatures, officeVersions,
  openOffice, openOfficeDocument, saveOffice, setOfficeAcl, setOfficeFeatures, textDocument,
} from "./office-support.mjs";

function descendants(value) {
  return [value, ...(value.content || []).flatMap(descendants)];
}

test("Office rich authoring saves confirmed native content and reopens from PostgreSQL/S3", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const writes = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.startsWith(OFFICE_PATH)) writes.push(request);
  });
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic Office rich document", { text: "Office overview" });
  await page.locator("#text-style").selectOption("heading-1");
  await officeEditor(page).press("Control+End");
  await officeEditor(page).press("Enter");
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.type("Important decision");
  await page.locator('[data-command="bold"]').click();
  await officeEditor(page).press("Enter");
  await page.locator('[data-command="bulletList"]').click();
  await page.keyboard.type("First action");
  await officeEditor(page).press("Enter");
  await officeEditor(page).press("Enter");
  await page.locator("#insert-menu").selectOption("insertTable");
  await page.keyboard.type("Owner");
  await expect(officeEditor(page).locator("h1")).toHaveText("Office overview");
  await expect(officeEditor(page).locator("strong")).toContainText("Important decision");
  await expect(officeEditor(page).locator("ul")).toContainText("First action");
  await expect(officeEditor(page).locator("table")).toContainText("Owner");
  expect(writes).toHaveLength(0);
  await page.locator("#find-toggle").click();
  await page.locator("#find-query").fill("decision");
  await expect(page.locator("#find-count")).toHaveText("1 / 1");
  await page.locator("#find-close").click();
  const saved = await saveOffice(page);
  expect(writes).toHaveLength(1);
  expect(writes[0].postDataJSON().human_confirmation).toBe(true);
  expect(descendants(saved.content).map((node) => node.type)).toEqual(expect.arrayContaining(["heading", "bulletList", "table", "tableHeader"]));
  expect(descendants(saved.content).some((node) => node.marks?.some((mark) => mark.type === "bold"))).toBe(true);
  await page.locator("#document-close").click();
  const loaded = await openOfficeDocument(page, saved.document.object_id);
  expect(loaded.content).toEqual(saved.content);
  expect(loaded.version.source_write_receipt_hash).toBe(saved.version.source_write_receipt_hash);
  await expect(officeEditor(page).locator("table")).toContainText("Owner");
  verifyBrowser();
});

test("Office edits produce immutable history and opening an earlier version is read-only", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic version history", "Initial saved text");
  await officeEditor(page).fill("Updated saved text");
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(second.version.previous_version_id).toBe(first.version.version_id);
  expect(second.version.version_id).not.toBe(first.version.version_id);
  expect((await officeVersions(page, first.document.object_id))).toHaveLength(2);
  const historical = await officeContent(page, first.document.object_id, { versionId: first.version.version_id });
  expect(historical.content).toEqual(first.content);
  expect(historical.is_current_version).toBe(false);
  await page.locator("#history-tab").click();
  await page.locator(`[data-version-id="${first.version.version_id}"]`).click();
  await expect(officeEditor(page)).toHaveText("Initial saved text");
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator("#document-status")).toContainText("Frühere Version");
  await page.locator("#document-reload").click();
  await expect(officeEditor(page)).toHaveText("Updated saved text");
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await expect(page.locator("#document-version")).toContainText(second.version.version_id);
});

test("Office concurrent editor conflict preserves the losing draft and committed head", async ({ page, context }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic concurrent document", "Original text");
  const other = await context.newPage();
  await openOffice(other);
  await openOfficeDocument(other, first.document.object_id);
  await officeEditor(other).fill("Losing draft remains local");
  await officeEditor(page).fill("Winning current version");
  const winner = await saveOffice(page, { objectId: first.document.object_id });
  await saveOffice(other, { objectId: first.document.object_id, status: 409 });
  await expect(officeEditor(other)).toHaveText("Losing draft remains local");
  await expect(other.locator("#document-notice")).toContainText("Ihr Entwurf wurde nicht überschrieben");
  await expect(other.locator("#document-save")).toBeDisabled();
  const current = await officeContent(page, first.document.object_id);
  expect(current.version.version_id).toBe(winner.version.version_id);
  expect(current.content).toEqual(winner.content);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office ordinary reader works with writes disabled while forged, foreign and read-only writes fail", async ({ page, context }) => {
  await openOffice(page);
  const created = await createOfficeDocument(page, "Synthetic reader document", "Authorized native document text");
  await setOfficeAcl(page, created.document.object_id);
  const reader = await context.newPage();
  const list = await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  expect(list.can_create).toBe(false);
  await expect(reader.locator("#document-new")).toBeDisabled();
  const loaded = await openOfficeDocument(reader, created.document.object_id);
  expect(loaded.can_write).toBe(false);
  await expect(officeEditor(reader)).toHaveAttribute("contenteditable", "false");
  await expect(officeEditor(reader)).toHaveText("Authorized native document text");
  await expect(reader.locator("#document-save")).toBeDisabled();
  const write = {
    title: created.document.title, document: textDocument("Forbidden replacement"),
    expected_current_version_id: created.version.version_id, mutation_reference: `read-denied-${Date.now()}`, human_confirmation: true,
  };
  for (const baseUrl of [BASE_URL, BLOCKED_BASE_URL]) {
    const response = await page.request.post(`${baseUrl}${OFFICE_PATH}/${created.document.object_id}/versions`, {
      headers: { ...OFFICE_READER_HEADERS, "X-Role-Ids": "office-editor", "X-Readable-Object-Ids": created.document.object_id }, data: write,
    });
    expect(response.status()).toBe(403);
  }
  for (const [headers, status] of [
    [{ ...OFFICE_HEADERS, "X-User-Id": "work-assignee-e2e", "X-Readable-Object-Ids": created.document.object_id }, 404],
    [{ ...OFFICE_HEADERS, "X-Tenant-Id": "tenant-demo", "X-Readable-Object-Ids": created.document.object_id }, 403],
  ]) {
    const response = await page.request.get(`${BASE_URL}${officeContentPath(created.document.object_id)}`, { headers });
    expect(response.status()).toBe(status);
    expect(await response.text()).not.toContain("Authorized native document text");
  }
  const missing = await page.request.get(`${BASE_URL}${officeContentPath("office-doc-" + "f".repeat(32))}`, { headers: OFFICE_HEADERS });
  expect(missing.status()).toBe(404);
  expect((await officeContent(page, created.document.object_id)).version.version_id).toBe(created.version.version_id);
});

test("Office current document ACL revocation also denies history and clears the editor", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic revocation document", "Revocation-sensitive text");
  await officeEditor(page).fill("Second protected version");
  await saveOffice(page, { objectId: first.document.object_id });
  await setOfficeAcl(page, first.document.object_id, { creator: true, status: "revoked" });
  try {
    for (const suffix of ["/content", `/content?version_id=${first.version.version_id}`, "/versions"]) {
      const response = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${first.document.object_id}${suffix}`, {
        headers: { ...OFFICE_HEADERS, "X-Readable-Object-Ids": first.document.object_id },
      });
      expect(response.status()).toBe(404);
      expect(await response.text()).not.toContain("protected version");
    }
    await page.locator("#document-reload").click();
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator("#document-title")).toHaveValue("");
    await expect(page.locator("#document-notice")).toContainText("nicht mehr freigegeben");
    await expect(page.locator("#document-save")).toBeDisabled();
  } finally {
    await setOfficeAcl(page, first.document.object_id, { creator: true });
  }
});

test("Office feature removal is rechecked on save and restores the exact synthetic feature mapping", async ({ page }) => {
  await openOffice(page);
  const created = await createOfficeDocument(page, "Synthetic feature-bound document", "Before feature closure");
  await officeEditor(page).fill("Unsaved text after feature closure");
  const previous = await officeFeatures(page);
  try {
    await setOfficeFeatures(page, { ...previous, "office_documents.documents.write": false });
    await saveOffice(page, { objectId: created.document.object_id, status: 403 });
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator("#documents-status")).toContainText("Zugriff wurde nicht bestätigt");
    const current = await officeContent(page, created.document.object_id);
    expect(current.content).toEqual(created.content);
    expect(current.can_write).toBe(false);
  } finally {
    await setOfficeFeatures(page, previous);
  }
});

test("Office pre-PUT storage failure leaves head unchanged and retries the same confirmed save", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic failed save", "Existing durable text");
  await officeEditor(page).fill("Recoverable saved draft");
  const attempts = [];
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  await page.route(`**${path}`, async (route) => {
    attempts.push(route.request().postDataJSON());
    await route.continue({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" } });
  }, { times: 1 });
  await saveOffice(page, { objectId: first.document.object_id, status: 503 });
  await expect(officeEditor(page)).toHaveText("Recoverable saved draft");
  await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
  expect((await officeContent(page, first.document.object_id)).version.version_id).toBe(first.version.version_id);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === path && request.method() === "POST") attempts.push(request.postDataJSON());
  });
  const retried = await saveOffice(page, { objectId: first.document.object_id });
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  expect(retried.version.previous_version_id).toBe(first.version.version_id);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office lost success response replays the actual committed version without duplication", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic uncertain response", "Initial committed text");
  await officeEditor(page).fill("Committed before response loss");
  const path = `${OFFICE_PATH}/${first.document.object_id}/versions`;
  let committed;
  await page.route(`**${path}`, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    committed = await response.json();
    await route.abort("connectionreset");
  }, { times: 1 });
  await page.locator("#document-save").click();
  await expect(page.locator("#save-dialog")).toBeVisible();
  await page.locator("#save-confirm").check();
  await page.locator("#save-submit").click();
  await expect(page.locator("#save-dialog")).toBeHidden();
  await expect(page.locator("#document-save")).toHaveText("Speicherung prüfen");
  await expect(officeEditor(page)).toHaveText("Committed before response loss");
  expect(committed.version.previous_version_id).toBe(first.version.version_id);
  const replay = await saveOffice(page, { objectId: first.document.object_id });
  expect(replay.replayed).toBe(true);
  expect(replay.version.version_id).toBe(committed.version.version_id);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
});

test("Office storage read failure clears old content and retry recovers real source bytes", async ({ page }) => {
  await openOffice(page);
  const created = await createOfficeDocument(page, "Synthetic unavailable content", "Storage-backed text");
  await page.route(`**${officeContentPath(created.document.object_id)}`, async (route) => {
    await route.continue({ headers: { ...route.request().headers(), "X-Work-E2E-Fail-Storage": "1" } });
  }, { times: 1 });
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(created.document.object_id));
  await page.locator("#document-reload").click();
  const failed = await pending;
  expect(failed.status()).toBe(503);
  expect(await failed.text()).not.toContain("Storage-backed text");
  await expect(page.locator("#office-editor")).toHaveText("");
  await expect(page.locator("#document-notice")).toContainText("konnte nicht geladen werden");
  await page.locator("#document-reload").click();
  await expect(officeEditor(page)).toHaveText("Storage-backed text");
  await expect(page.locator("#document-notice")).toBeHidden();
});

test("Office renders malicious markup literally and ignores a content response after close", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  const text = '<img src="https://invalid.example/pixel" onerror="window.officeAttack=true"><script>window.officeAttack=true</script>';
  await openOffice(page);
  const created = await createOfficeDocument(page, "Synthetic literal document", text);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, created.document.object_id);
  await expect(officeEditor(page)).toHaveText(text);
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
  expect(await page.evaluate(() => window.officeAttack)).toBeUndefined();
  await page.locator("#document-close").click();
  await observeStaleOfficeContent(page, text);
  const delayed = await holdOfficeRead(page, created.document.object_id);
  try {
    await page.locator(`[data-document-id="${created.document.object_id}"]`).click();
    await delayed.ready;
    await page.locator("#document-close").click();
    await expect(page.locator("#document-workspace")).toBeHidden();
    await delayed.complete();
    await expect(page.locator("#office-editor")).toHaveText("");
    expect(await page.evaluate(() => window.staleOfficeContent)).toBe(false);
  } finally { delayed.release(); }
  verifyBrowser();
});

test("Office suppresses late content when context changes to an unauthorized principal", async ({ page }) => {
  await openOffice(page);
  const created = await createOfficeDocument(page, "Synthetic context-bound document", "Previous authorized context text");
  await page.locator("#document-close").click();
  await observeStaleOfficeContent(page, "Previous authorized context text");
  const delayed = await holdOfficeRead(page, created.document.object_id);
  try {
    await page.locator(`[data-document-id="${created.document.object_id}"]`).click();
    await delayed.ready;
    await page.locator("#context-toggle").click();
    await page.locator("#user-id").fill("work-assignee-e2e");
    await page.locator("#role-ids").fill("office-reader");
    await page.locator("#readable-object-ids").fill(created.document.object_id);
    await page.locator('#context-form button[type="submit"]').click();
    await expect(page.locator("#documents-refresh")).toBeEnabled();
    await expect(page.locator("#document-workspace")).toBeHidden();
    await delayed.complete();
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator(`[data-document-id="${created.document.object_id}"]`)).toHaveCount(0);
    expect(await page.evaluate(() => window.staleOfficeContent)).toBe(false);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("collabio.workspace.context")).userId)).not.toBe(OFFICE_EDITOR_ID);
  } finally { delayed.release(); }
});
