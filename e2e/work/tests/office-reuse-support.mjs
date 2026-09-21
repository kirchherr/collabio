import { expect } from "@playwright/test";

import { BASE_URL } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_PATH, captureOfficeResponse, officeContentPath, officeEditor } from "./office-support.mjs";

export const reuseContentMatch = (objectId, versionId) => (url) => url.pathname === officeContentPath(objectId) && url.searchParams.get("version_id") === versionId;

export function collectReuseRequests(page) {
  const requests = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith(OFFICE_PATH)) requests.push({ method: request.method(), path: url.pathname, versionId: url.searchParams.get("version_id"), body: request.method() === "POST" ? request.postDataJSON() : null });
  });
  return requests;
}

export async function openReuse(page, saved, title = null) {
  await page.locator("#document-reuse").click();
  await expect(page.locator("#reuse-dialog")).toBeVisible();
  await expect(page.locator("#reuse-source")).toContainText(saved.version.title);
  await expect(page.locator("#reuse-source")).toContainText("gespeicherte Fassung");
  if (title !== null) await page.locator("#reuse-title").fill(title);
}

export async function submitReuse(page, saved, { status = 200, extraHeaders = {} } = {}) {
  const matches = reuseContentMatch(saved.document.object_id, saved.version.version_id);
  const captured = await captureOfficeResponse(page, matches, { extraHeaders });
  const listing = status === 200 ? await captureOfficeResponse(page, (url) => url.pathname === OFFICE_PATH) : null;
  const pending = page.waitForResponse((response) => matches(new URL(response.url())) && response.request().method() === "GET");
  await page.locator("#reuse-submit").click();
  const browser = await pending;
  const source = await captured.received;
  expect(browser.status()).toBe(status);
  expect(browser.headers()["cache-control"]).toContain("no-store");
  expect(source.status).toBe(status);
  expect(source.headers["cache-control"]).toContain("no-store");
  if (status !== 200) {
    expect(source.json.detail).toBe(status === 404 ? "Document not found" : "Office storage unavailable");
    return { source: source.json, listing: null };
  }
  expect(source.json.document.object_id).toBe(saved.document.object_id);
  expect(source.json.version.version_id).toBe(saved.version.version_id);
  expect(source.json.content).toEqual(saved.content);
  const capabilities = await listing.received;
  expect(capabilities.status).toBe(200);
  expect(capabilities.headers["cache-control"]).toContain("no-store");
  expect(capabilities.json.tenant_id).toBe(source.json.tenant_id);
  return { source: source.json, listing: capabilities.json };
}

export async function expectReuseDraft(page, title) {
  await expect(page.locator("#reuse-dialog")).toBeHidden();
  await expect(page.locator("#document-title")).toHaveValue(title);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  await expect(page.locator("#document-save")).toBeEnabled();
  await expect(page.locator("#document-reuse")).toBeDisabled();
  await expect(page.locator("#document-notice")).toContainText("als neues, ungespeichertes Dokument übernommen");
  await expect(page.locator("#document-history [data-version-id]")).toHaveCount(0);
  await expect(page.locator("#comments-toggle")).toBeDisabled();
  await expect(page.locator("#suggestions-toggle")).toBeDisabled();
}

export async function openReuseHistory(page, saved) {
  if (!await page.locator("#history-tab").isVisible()) await page.locator("#inspector-toggle").click();
  await page.locator("#history-tab").click();
  const pending = page.waitForResponse((response) => reuseContentMatch(saved.document.object_id, saved.version.version_id)(new URL(response.url())));
  await page.locator(`[data-version-id="${saved.version.version_id}"]`).click();
  expect((await pending).status()).toBe(200);
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "false");
}

export async function createReusableSource(page) {
  const paragraph = (text, marks = []) => ({ type: "paragraph", content: [{ type: "text", text, ...(marks.length ? { marks } : {}) }] });
  const response = await page.request.post(`${BASE_URL}${OFFICE_PATH}`, {
    headers: OFFICE_HEADERS,
    data: {
      title: "Historical reuse <b>literal title</b> 😀", mutation_reference: `reuse-source-${crypto.randomUUID()}`, human_confirmation: true,
      document: { type: "doc", content: [
        { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Saved source heading" }] },
        paragraph("Original selected wording", [{ type: "bold" }, { type: "italic" }]),
        paragraph('<img src="https://reuse.invalid/leak" onerror="window.reuseExecuted=true">'),
        { type: "bulletList", content: [{ type: "listItem", content: [paragraph("Saved list item")] }] },
        { type: "table", content: [
          { type: "tableRow", content: ["Owner", "Decision"].map((text) => ({ type: "tableHeader", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text)] })) },
          { type: "tableRow", content: ["Team", "Keep original marks"].map((text) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text, [{ type: "underline" }])] })) },
        ] },
      ] },
    },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

export async function observeReuseDraft(page, title) {
  await page.evaluate((unexpectedTitle) => {
    window.staleReuseDraft = false;
    new MutationObserver(() => {
      window.staleReuseDraft ||= document.querySelector("#document-title").value === unexpectedTitle;
    }).observe(document.querySelector("#document-workspace"), { subtree: true, childList: true, characterData: true, attributes: true });
  }, title);
}
