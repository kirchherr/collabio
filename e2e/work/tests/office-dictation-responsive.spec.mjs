import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import {
  createOfficeDocument,
  dictateIntoOffice,
  installSyntheticSpeechRecognition,
  officeEditor,
  officeVersions,
  openOffice,
} from "./office-support.mjs";

test("Office push-to-talk dictation remains a local responsive draft until explicit save", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await installSyntheticSpeechRecognition(page);
  await openOffice(page);
  const created = await createOfficeDocument(
    page,
    `Synthetic dictation ${testInfo.project.name}`,
    "Confirmed source sentence.",
  );
  const objectId = created.document.object_id;
  await expect(page.locator("#dictation-status")).toContainText("kein Roh-Audio in Collabio");
  const transcript = `Dictation ${testInfo.project.name} stays local until save.`;

  await dictateIntoOffice(page, objectId, transcript);

  await expect(page.locator("#document-save")).toBeEnabled();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  await expect(officeEditor(page)).toContainText(transcript);
  expect(await page.locator("#dictation-push").evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-dictation-${testInfo.project.name}.png`, fullPage: true });
  verifyBrowser();
});
