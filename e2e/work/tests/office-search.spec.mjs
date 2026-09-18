import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, createOfficeDocument, createOfficeVersionPair,
  holdOfficeRead, loadOfficeComparison, newOfficeDraft, observeStaleOfficeContent,
  officeContent, officeEditor, officeVersions, openOffice, openOfficeComparison,
  openOfficeDocument, saveOffice, setOfficeAcl,
} from "./office-support.mjs";

async function find(page, query, replacement) {
  if (!await page.locator("#find-panel").isVisible()) await page.locator("#find-toggle").click();
  await page.locator("#find-query").fill(query);
  if (replacement !== undefined) await page.locator("#replace-query").fill(replacement);
}

function collectWrites(page) {
  const writes = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.startsWith(OFFICE_PATH)) writes.push(request.postDataJSON());
  });
  return writes;
}

test("Office literal Unicode search crosses marks and saves a confirmed replacement as a new immutable version", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  await newOfficeDraft(page, "Synthetic Unicode search", { text: "" });
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.type("Ca");
  await page.locator('[data-command="bold"]').click();
  await page.keyboard.type("fé CAFÉ Caféteria café猫 [a.*] [a.*]");
  const original = "Café CAFÉ Caféteria café猫 [a.*] [a.*]";
  const first = await saveOffice(page);
  expect(first.content.content[0].content.some((part) => part.marks?.some((mark) => mark.type === "bold"))).toBe(true);
  const writes = collectWrites(page);
  await officeEditor(page).press("Control+f");
  await expect(page.locator("#find-query")).toBeFocused();
  await find(page, "[a.*]");
  await expect(page.locator("#find-count")).toHaveText("1 / 2");
  await page.locator("#find-query").press("Enter");
  await expect(page.locator("#find-count")).toHaveText("2 / 2");
  await page.locator("#find-query").press("Shift+Enter");
  await expect(page.locator("#find-count")).toHaveText("1 / 2");
  await find(page, "Café", "Tea");
  await expect(page.locator("#find-count")).toHaveText("1 / 4");
  await page.locator("#find-whole-word").check();
  await expect(page.locator("#find-count")).toHaveText("1 / 2");
  await page.locator("#find-case-sensitive").check();
  await expect(page.locator("#find-count")).toHaveText("1 / 1");
  await page.locator("#replace-current").click();
  await expect(officeEditor(page)).toHaveText("Tea CAFÉ Caféteria café猫 [a.*] [a.*]");
  await expect(page.locator("#find-message")).toContainText("1 Treffer ersetzt");
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  await page.locator("#find-close").click();
  const second = await saveOffice(page, { objectId: first.document.object_id });
  expect(writes).toHaveLength(1);
  expect(writes[0].human_confirmation).toBe(true);
  expect(second.version.previous_version_id).toBe(first.version.version_id);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await expect(officeEditor(page)).toHaveText("Tea CAFÉ Caféteria café猫 [a.*] [a.*]");
  await openOfficeComparison(page);
  await loadOfficeComparison(page, first.document.object_id, first.version.version_id, second.version.version_id);
  await expect(page.locator("#compare-results")).toContainText("CAFÉ Caféteria café猫 [a.*] [a.*]");
  await expect(page.locator("#compare-results")).toContainText("Tea");
  expect(first.content.content[0].content.map((part) => part.text || "").join("")).toBe(original);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(2);
  verifyBrowser();
});

test("Office replace all is one undo step isolated from typing before and after it", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic replacement undo", "north north");
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await officeEditor(page).press("Control+End");
  await page.keyboard.type(" before");
  await officeEditor(page).press("Control+h");
  await expect(page.locator("#replace-query")).toBeFocused();
  await find(page, "north", "east");
  await page.locator("#replace-all").click();
  await expect(officeEditor(page)).toHaveText("east east before");
  await page.locator("#replace-query").press("Escape");
  await expect(page.locator("#find-panel")).toBeHidden();
  await officeEditor(page).press("Control+End");
  await page.keyboard.type(" after");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page)).toHaveText("east east before");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page)).toHaveText("north north before");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page)).toHaveText("north north");
  await officeEditor(page).press("Control+Shift+z");
  await expect(officeEditor(page)).toHaveText("north north before");
  await officeEditor(page).press("Control+Shift+z");
  await expect(officeEditor(page)).toHaveText("east east before");
  await officeEditor(page).press("Control+Shift+z");
  await expect(officeEditor(page)).toHaveText("east east before after");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office replacement treats hostile markup and replacement metacharacters as literal saved text", async ({ page }) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic literal replacement", "token token");
  const literal = '<img src="https://invalid.example/replace" onerror="window.replaceAttack=true"><script>window.replaceAttack=true</script>$&$1';
  await find(page, "token", literal);
  await page.locator("#replace-all").click();
  await expect(officeEditor(page)).toHaveText(`${literal} ${literal}`);
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
  expect(await page.evaluate(() => window.replaceAttack)).toBeUndefined();
  await page.locator("#find-close").click();
  const saved = await saveOffice(page, { objectId: first.document.object_id });
  expect(saved.version.previous_version_id).toBe(first.version.version_id);
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  await expect(officeEditor(page)).toHaveText(`${literal} ${literal}`);
  await expect(officeEditor(page).locator("img,script")).toHaveCount(0);
  verifyBrowser();
});

test("Office counts more than a thousand matches and replaces every match beyond the highlight window", async ({ page }) => {
  await openOffice(page);
  const original = Array(1005).fill("needle").join(" ");
  const expected = Array(1005).fill("thread").join(" ");
  const first = await createOfficeDocument(page, "Synthetic complete match count", original);
  const writes = collectWrites(page);
  await find(page, "needle", "thread");
  await expect(page.locator("#find-count")).toHaveText("1 / 1005");
  await expect(page.locator("#find-highlight-note")).toContainText("von 1005");
  expect(await officeEditor(page).locator(".search-match").count()).toBeLessThanOrEqual(200);
  await page.locator("#find-query").press("Shift+Enter");
  await expect(page.locator("#find-count")).toHaveText("1005 / 1005");
  await expect(officeEditor(page).locator(".search-match.current")).toHaveText("needle");
  await page.locator("#replace-all").click();
  await expect(officeEditor(page)).toHaveText(expected);
  await expect(page.locator("#find-count")).toHaveText("0 Treffer");
  await expect(page.locator("#find-message")).toContainText("1005 Treffer ersetzt");
  await page.locator("#find-close").click();
  await page.locator('[data-command="undo"]').click();
  await expect(officeEditor(page)).toHaveText(original);
  await page.locator('[data-command="redo"]').click();
  await expect(officeEditor(page)).toHaveText(expected);
  expect(writes).toHaveLength(0);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office ordinary readers and historical views can search but cannot replace", async ({ page, context }) => {
  await openOffice(page);
  const pair = await createOfficeVersionPair(page, "Synthetic search permissions", "needle in history", "needle in current");
  await setOfficeAcl(page, pair.objectId);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, pair.objectId);
  await find(reader, "needle");
  await expect(reader.locator("#find-count")).toHaveText("1 / 1");
  for (const id of ["replace-query", "replace-current", "replace-all"]) await expect(reader.locator(`#${id}`)).toBeDisabled();
  await expect(reader.locator("#find-message")).toContainText("Schreibgeschützt");
  await expect(officeEditor(reader)).toHaveText("needle in current");
  await page.locator("#history-tab").click();
  await page.locator(`[data-version-id="${pair.first.version.version_id}"]`).click();
  await expect(officeEditor(page)).toHaveText("needle in history");
  await find(page, "needle");
  await expect(page.locator("#find-count")).toHaveText("1 / 1");
  for (const id of ["replace-query", "replace-current", "replace-all"]) await expect(page.locator(`#${id}`)).toBeDisabled();
  await expect(page.locator("#find-message")).toContainText("Schreibgeschützt");
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
});

test("Office no-op and oversized replacements preserve clean state while empty replacement removes text locally", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic replacement bounds", "keep target target");
  await page.locator("#document-close").click();
  await openOfficeDocument(page, first.document.object_id);
  const writes = collectWrites(page);
  await find(page, "target", "target");
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await page.locator("#replace-all").click();
  await expect(page.locator("#find-message")).toContainText("Keine Änderung");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await page.locator("#replace-query").fill("X".repeat(60000));
  await page.locator("#replace-all").click();
  await expect(page.locator("#find-message")).toContainText("überschreitet die unterstützte Dokumentgröße");
  await expect(officeEditor(page)).toHaveText("keep target target");
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator('[data-command="undo"]')).toBeDisabled();
  await page.locator("#replace-query").fill("");
  await page.locator("#replace-all").click();
  expect(await officeEditor(page).textContent()).toBe("keep  ");
  await expect(page.locator("#find-count")).toHaveText("0 Treffer");
  await expect(page.locator("#document-save")).toBeEnabled();
  await page.locator("#find-query").fill("");
  await expect(page.locator("#replace-current")).toBeDisabled();
  await expect(page.locator("#replace-all")).toBeDisabled();
  expect(writes).toHaveLength(0);
  expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
});

test("Office preserves replacement drafts on discard cancellation and clears search across context and late reads", async ({ page }) => {
  await openOffice(page);
  const first = await createOfficeDocument(page, "Synthetic search context", "Private original token");
  await find(page, "token", "replacement draft");
  await page.locator("#replace-all").click();
  await expect(officeEditor(page)).toHaveText("Private original replacement draft");
  await page.locator("#document-close").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-cancel").click();
  await expect(officeEditor(page)).toHaveText("Private original replacement draft");
  await expect(page.locator("#find-query")).toHaveValue("token");
  await expect(page.locator("#replace-query")).toHaveValue("replacement draft");
  const held = await holdOfficeRead(page, first.document.object_id);
  try {
    await page.locator("#document-reload").click();
    await page.locator("#discard-confirm").click();
    await held.ready;
    await observeStaleOfficeContent(page, "Private original token");
    await page.locator("#context-toggle").click();
    await page.locator("#user-id").fill("work-assignee-e2e");
    await page.locator("#role-ids").fill("office-reader");
    await page.locator("#readable-object-ids").fill(first.document.object_id);
    await page.locator('#context-form button[type="submit"]').click();
    await expect(page.locator("#documents-refresh")).toBeEnabled();
    await expect(page.locator("#document-workspace")).toBeHidden();
    await held.complete();
    await expect(page.locator("#office-editor")).toHaveText("");
    await expect(page.locator("#find-panel")).toBeHidden();
    await expect(page.locator("#find-query")).toHaveValue("");
    await expect(page.locator("#replace-query")).toHaveValue("");
    expect(await page.evaluate(() => window.staleOfficeContent)).toBe(false);
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("replacement draft");
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("Private original token");
    expect((await officeContent(page, first.document.object_id)).content).toEqual(first.content);
  } finally { held.release(); }
});
