import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import {
  createOfficeDocument,
  installSyntheticSpeechSynthesis,
  officeEditor,
  officeVersions,
  openOffice,
  readOfficeSelectionAloud,
} from "./office-support.mjs";

test("Office read aloud uses an authorized saved selection without storing audio", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await installSyntheticSpeechSynthesis(page);
  await openOffice(page);
  const source = `Saved read aloud selection for ${testInfo.project.name}.`;
  const created = await createOfficeDocument(page, `Synthetic read aloud ${testInfo.project.name}`, source);
  const objectId = created.document.object_id;

  await expect(page.locator("#read-aloud-status")).toContainText("Markieren Sie bis zu 2.000 Zeichen");
  const prepared = await readOfficeSelectionAloud(page, objectId);

  expect(prepared.source_text).toBe(source);
  expect(await page.evaluate(() => window.__officeSyntheticSpeechSynthesis.state.spoken)).toEqual([
    { text: source, lang: "de-DE", rate: 1, localService: true },
  ]);
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await expect(page.locator("#document-save")).toBeDisabled();
  await page.evaluate(() => window.__officeSyntheticSpeechSynthesis.finish());
  await expect(page.locator("#read-aloud-status")).toContainText("vollständig vorgelesen");
  await expect(officeEditor(page)).toContainText(source);
  expect(await page.locator("#read-aloud").evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-read-aloud-${testInfo.project.name}.png`, fullPage: true });
  verifyBrowser();
});
