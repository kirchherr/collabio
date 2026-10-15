import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeVersions, openOffice, openOfficeDocument, showDocumentList } from "./office-support.mjs";
import { answerDocumentQuestion, openSuggestions } from "./office-suggestion-support.mjs";

test("Office answers document questions with exact current-version citations on desktop and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const current = await createOfficeDocument(
    page,
    `Synthetic RAG question ${testInfo.project.name}`,
    "Which approval is required before publication?",
  );
  await showDocumentList(page);
  const sourceToken = `rag-${testInfo.project.name}-${Date.now()}`;
  const source = await createOfficeDocument(
    page,
    `Synthetic RAG source ${sourceToken}`,
    `${sourceToken} requires manager approval before customer commitments are published.`,
  );
  await openOfficeDocument(page, current.document.object_id);
  await openSuggestions(page, current.document.object_id);

  const answer = await answerDocumentQuestion(
    page,
    current.document.object_id,
    `Who approves ${sourceToken}?`,
    source,
  );

  expect(answer.citations).toHaveLength(1);
  expect(await officeVersions(page, current.document.object_id)).toHaveLength(1);
  expect(await officeVersions(page, source.document.object_id)).toHaveLength(1);
  await expect(page.locator("#suggestion-rag-report")).toBeInViewport();
  expect(await page.locator("#suggestions-panel").evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-rag-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#suggestion-rag-dismiss").click();
  await expect(page.locator("#suggestion-rag-report")).toBeHidden();
  verifyBrowser();
});
