import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, officeVersions, openOffice, openOfficeDocument, showDocumentList } from "./office-support.mjs";
import { compareDocumentWithPolicy, confirmSuggestion, markDocumentRisks, openSuggestion, openSuggestions, outlineSuggestion, prepareSuggestion, prepareSuggestionDecision, rewriteSuggestion, summarizeSuggestion, translateSuggestion } from "./office-suggestion-support.mjs";

async function expectSuggestionLayout(page) {
  await expect(page.locator("#suggestions-panel")).toBeInViewport();
  for (const selector of ["#suggestions-refresh", "#suggestion-quote", "#suggestion-after", '[data-suggestion-action="accept"]', '[data-suggestion-action="reject"]']) {
    await page.locator(selector).scrollIntoViewIfNeeded();
    await expect(page.locator(selector)).toBeInViewport();
    await expect(page.locator("#suggestions-close")).toBeInViewport();
  }
  expect(await page.locator("#suggestions-panel").evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("Office text proposals and confirmed decisions fit desktop, tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const first = await createOfficeDocument(page, `Synthetic responsive suggestion ${testInfo.project.name}`, "Plan 😀 review: responsible team confirms the next step.");
  const objectId = first.document.object_id;
  await showDocumentList(page);
  const policy = await createOfficeDocument(page, `Synthetic approval policy ${testInfo.project.name}`, "POLICY requires manager approval before milestone 42 is committed.");
  await openOfficeDocument(page, objectId);
  await openSuggestions(page, objectId);
  await markDocumentRisks(page, objectId);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-risk-dismiss").click();
  await expect(page.locator("#suggestion-risk-report")).toBeHidden();
  await compareDocumentWithPolicy(page, objectId, policy);
  await expect(page.locator("#suggestion-policy-citation")).toContainText(policy.document.title);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  expect(await officeVersions(page, policy.document.object_id)).toHaveLength(1);
  await page.locator("#suggestion-policy-dismiss").click();
  await expect(page.locator("#suggestion-policy-report")).toBeHidden();
  await summarizeSuggestion(page, objectId, "responsible team confirms the next step");
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await rewriteSuggestion(page, objectId, "responsible team confirms the next step");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await rewriteSuggestion(page, objectId, "responsible team confirms the next step", { operation: "tone", tone: "friendly" });
  await expect(page.locator("#suggestion-ai-label")).toContainText("Ton: Freundlich");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await translateSuggestion(page, objectId, "responsible team confirms the next step", "de");
  await expect(page.locator("#suggestion-ai-label")).toContainText("Zielsprache: Deutsch");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await outlineSuggestion(page, objectId, "responsible team confirms the next step", "detailed");
  await expect(page.locator("#suggestion-ai-label")).toContainText("Detaillierte Gliederung");
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await page.locator("#suggestion-cancel").click();
  await expect(page.locator("#discard-dialog")).toBeVisible();
  await page.locator("#discard-confirm").click();
  await prepareSuggestion(page, "Plan 😀 review", "Approved 😀 review");
  for (const id of ["suggestion-confirm-checkbox", "suggestion-confirm-submit", "suggestion-confirm-cancel"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await page.locator("#suggestion-confirm-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
  const created = await confirmSuggestion(page, objectId);
  const suggestionId = created.suggestion.suggestion_id;
  await openSuggestion(page, objectId, suggestionId);
  await expectSuggestionLayout(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-suggestions-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expect(page.locator("#document-inspector")).toBeHidden();
    await openSuggestions(page, objectId);
    await openSuggestion(page, objectId, suggestionId);
    await expectSuggestionLayout(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-suggestions-tablet-chromium.png`, fullPage: true });
  }
  await prepareSuggestionDecision(page, suggestionId, "accept");
  await expect(page.locator("#suggestion-confirm-submit")).toBeInViewport();
  const accepted = await confirmSuggestion(page, objectId, { suggestionId });
  expect(accepted.document_result.version.previous_version_id).toBe(first.version.version_id);
  await page.locator("#suggestions-close").click();
  await expect(officeEditor(page)).toBeInViewport();
  await expect(officeEditor(page)).toHaveText("Approved 😀 review: responsible team confirms the next step.");
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, objectId)).toHaveLength(2);
  verifyBrowser();
});
