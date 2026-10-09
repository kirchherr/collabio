import { expect, test } from "@playwright/test";

import { createOfficeDocument, officeEditor, openOffice, openOfficeDocument, saveOffice, setOfficeAcl, showDocumentList } from "./office-support.mjs";
import { ARTIFACT_DIR } from "./support.mjs";

const cards = (page) => officeEditor(page).locator("[data-office-document-card]");

test("Office document objects pin refresh manage save and print exact authorized versions", async ({ page }, testInfo) => {
  await openOffice(page);
  const targetV1 = await createOfficeDocument(page, "Object target v1", "Object target body one");
  await showDocumentList(page);
  const source = await createOfficeDocument(page, "Object source", "Before object\nAfter object");

  await page.locator("#document-card-options").click();
  await expect(page.locator("#document-card-dialog")).toBeVisible();
  await page.locator("#document-card-target").selectOption({ label: "Object target v1" });
  await page.locator("#document-card-mode").selectOption("linked");
  await page.locator("#document-card-apply").click();
  await expect(cards(page)).toHaveCount(1);
  await expect(cards(page)).toHaveAttribute("data-office-document-version", targetV1.version.version_id);
  await page.locator('[data-command="undo"]').click(); await expect(cards(page)).toHaveCount(0);
  await page.locator('[data-command="redo"]').click(); await expect(cards(page)).toHaveCount(1);
  const sourceV2 = await saveOffice(page, { objectId: source.document.object_id });
  expect(sourceV2.content.content.some((entry) => entry.type === "documentCard" && entry.attrs.mode === "linked")).toBe(true);

  await openOfficeDocument(page, targetV1.document.object_id);
  await page.locator("#document-title").fill("Object target v2");
  await officeEditor(page).fill("Object target body two");
  const targetV2 = await saveOffice(page, { objectId: targetV1.document.object_id });
  await openOfficeDocument(page, source.document.object_id);
  await expect(cards(page)).toContainText("Object target v1");
  await cards(page).locator(".office-document-card-edit").click();
  await expect(page.locator("#document-card-refresh")).toBeEnabled();
  await page.locator("#document-card-refresh").click();
  await expect(cards(page)).toHaveAttribute("data-office-document-version", targetV2.version.version_id);
  await expect(cards(page)).toContainText("Object target v2");

  await cards(page).locator(".office-document-card-edit").click();
  await page.locator("#document-card-duplicate").click();
  await expect(cards(page)).toHaveCount(2);
  await cards(page).nth(1).locator(".office-document-card-edit").click();
  await expect(page.locator("#document-card-previous")).toBeEnabled();
  await page.locator("#document-card-previous").click();
  await cards(page).first().locator(".office-document-card-edit").click();
  await page.locator("#document-card-remove").click();
  await expect(cards(page)).toHaveCount(1);

  const saved = await saveOffice(page, { objectId: source.document.object_id });
  const savedCards = saved.content.content.filter((entry) => entry.type === "documentCard");
  expect(savedCards).toEqual([{ type: "documentCard", attrs: {
    targetObjectId: targetV1.document.object_id, targetVersionId: targetV2.version.version_id, mode: "linked",
  } }]);
  await openOfficeDocument(page, source.document.object_id);
  await expect(cards(page)).toContainText("Object target v2");
  await page.locator("#document-print").click();
  await expect(page.locator("#print-preview .office-print-document-card")).toContainText("Object target v2");
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-document-card-${testInfo.project.name}.png`, fullPage: true });
  await page.locator("#print-close").click();

  await setOfficeAcl(page, targetV1.document.object_id, { status: "revoked", creator: true });
  try {
    await openOfficeDocument(page, source.document.object_id);
    await expect(cards(page)).toHaveAttribute("data-office-reference-status", "unavailable");
    await expect(cards(page)).toContainText("Dokumentobjekt nicht verfügbar");
    await expect(cards(page)).not.toContainText("Object target v2");
    await page.locator("#document-print").click();
    await expect(page.locator("#print-preview .office-print-document-card")).toHaveAttribute("data-office-reference-status", "unavailable");
    await expect(page.locator("#print-preview")).not.toContainText("Object target v2");
  } finally {
    await setOfficeAcl(page, targetV1.document.object_id, { status: "active", creator: true });
  }
});
