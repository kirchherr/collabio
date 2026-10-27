import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const PROVENANCE = {
  sourceObjectId: "source-docx-review",
  sourceVersionId: "v3",
  sourceContentHash: HASH_A,
  sourceAclVersion: 7,
  parserProfileId: "rich-document-parser-worker:1",
  parserTextHash: HASH_B,
  importScope: "bounded_flattened_text_preview",
};

test("Office creates and saves an ACL-bound non-persisting DOCX import preview", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  await page.route("**/v1/office/documents/import-previews", async (route) => {
    const request = route.request(), body = request.postDataJSON();
    expect(body).toEqual({ source_object_id: "source-docx-review", source_version_id: "v3" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "office_import_preview.v1",
        tenant_id: "tenant-work-e2e",
        source_object_id: "source-docx-review",
        source_version_id: "v3",
        source_title: "Importierte DOCX-Notiz",
        source_content_hash: HASH_A,
        source_acl_version: 7,
        information_classification: "confidential",
        parser_profile_id: "rich-document-parser-worker:1",
        parser_text_hash: HASH_B,
        warnings: ["non-executable security markers require review"],
        document: { type: "doc", attrs: { importProvenance: PROVENANCE }, content: [
          { type: "paragraph", content: [{ type: "text", text: "Sicher importierter Inhalt" }] },
          { type: "paragraph", content: [{ type: "text", text: "Formatierungen können abgeflacht sein." }] },
        ] },
        content_persisted: false,
        save_requires_explicit_confirmation: true,
        fidelity_preserved: false,
        import_scope: "bounded_flattened_text_preview",
        audit_event_id: "audit-import-preview-review",
      }),
    });
  });
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  await page.locator("#document-import").click();
  const dialog = page.locator("#import-document-dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator('[name="source_object_id"]').fill("source-docx-review");
  await dialog.locator('[name="source_version_id"]').fill("v3");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();

  await expect(officeEditor(page)).toContainText("Sicher importierter Inhalt");
  await expect(page.locator("#document-mode")).toHaveText("Importvorschau");
  await expect(page.locator("#document-version")).toContainText("Quelle v3");
  await expect(page.locator("#document-classification")).toHaveValue("confidential");
  await expect(page.locator("#document-notice")).toContainText("Formatierungen können abgeflacht sein");

  const saved = await saveOffice(page);
  const persisted = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(persisted.content.attrs.importProvenance).toEqual(PROVENANCE);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page)).toContainText("Sicher importierter Inhalt");
  const viewport = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(viewport.overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-import-preview-${testInfo.project.name}.png`, fullPage: true });
});
