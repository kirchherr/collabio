import { expect } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, TENANT_ID } from "./support.mjs";
import { KB_HEADERS, openKnowledge } from "./knowledge-support.mjs";

export const READER_ID = "work-reader-e2e";
export const READER_HEADERS = {
  "X-Tenant-Id": TENANT_ID,
  "X-User-Id": READER_ID,
  "X-Role-Ids": "knowledge-reader",
};

export function contentPath(articleId) {
  return `/v1/kb/articles/${encodeURIComponent(articleId)}/content`;
}

export async function setReaderAcl(page, objectId, objectType, status = "active") {
  const response = await page.request.post(`${BASE_URL}/v1/admin/authz/object-acl-entries`, {
    headers: { ...KB_HEADERS, "X-Role-Ids": "security-admin" },
    data: {
      object_id: objectId,
      object_type: objectType,
      acl_subject_type: "user",
      acl_subject_id: READER_ID,
      permission: "read",
      acl_version: 1,
      status,
      approval_reference: "test-fixture:work-e2e-reader-acl",
      reason: "Synthetic isolated browser reader proof only",
    },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe(status);
}

export async function grantReaderAccess(page, created) {
  await setReaderAcl(page, created.article_object_id, "kb.article");
  await setReaderAcl(page, created.current_version_object_id, "kb.article_version");
}

export async function openReaderWorkspace(page) {
  await openKnowledge(page, { baseUrl: BLOCKED_BASE_URL, userId: READER_ID, roleIds: "knowledge-reader" });
  await expect(page.locator("#knowledge-create")).toBeHidden();
  await expect(page.locator("[data-knowledge-edit]")).toHaveCount(0);
}

export async function readArticle(page, articleId, { refresh = false, status = 200 } = {}) {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === contentPath(articleId));
  await page.locator(refresh ? "#knowledge-reader-refresh" : `[data-knowledge-read="${articleId}"]`).click();
  const response = await pending;
  expect(response.status()).toBe(status);
  const result = await response.json();
  if (status === 200) {
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.article.object_id).toBe(articleId);
    expect(result.rag_indexing_allowed).toBe(false);
    expect(result.search_indexing_allowed).toBe(false);
    expect(result.audit_event_id).toBeTruthy();
    await expect(page.locator("#knowledge-reader-title")).toHaveText(result.article.title);
    await expect(page.locator("#knowledge-reader-body")).toHaveText(result.body, { useInnerText: false });
    await expect(page.locator("#knowledge-reader-version")).toContainText(result.article.current_version_object_id);
    await expect(page.locator("#knowledge-reader-version")).toContainText(result.article.current_version_label);
    await expect(page.locator("#knowledge-reader-updated")).toHaveAttribute("datetime", /.+/);
  }
  await expect(page.locator("#knowledge-reader-refresh")).toBeEnabled();
  return result;
}

export async function closeReader(page) {
  await page.locator("#knowledge-reader-close").click();
  await expect(page.locator("#knowledge-reader-dialog")).toBeHidden();
  await expect(page.locator("#knowledge-reader-body")).toHaveText("");
  await expect(page.locator("#knowledge-reader-version")).toHaveText("");
}

export async function holdContentResponse(page, articleId) {
  let release;
  let started;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  await page.route(`**${contentPath(articleId)}`, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    started();
    await gate;
    await route.fulfill({ response });
  }, { times: 1 });
  return {
    ready,
    release,
    async complete() {
      const pending = page.waitForResponse((response) => new URL(response.url()).pathname === contentPath(articleId));
      release();
      await (await pending).finished();
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    },
  };
}

export async function watchForStaleReaderContent(page, body) {
  await page.evaluate((staleBody) => {
    window.staleReaderContent = false;
    const inspect = () => {
      window.staleReaderContent ||= document.querySelector("#knowledge-reader-body").textContent.includes(staleBody);
    };
    new MutationObserver(inspect).observe(document.querySelector("#knowledge-reader-dialog"), {
      subtree: true, childList: true, characterData: true,
    });
    inspect();
  }, body);
}
