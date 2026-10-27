import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { officeContent, officeEditor, openOffice, openOfficeDocument, saveOffice } from "./office-support.mjs";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const HASH_C = `sha256:${"c".repeat(64)}`;
const PROVENANCE = {
  sourceObjectId: "source-docx-review",
  sourceVersionId: "v3",
  sourceContentHash: HASH_A,
  sourceAclVersion: 7,
  parserProfileId: "rich-document-parser-worker:1",
  parserTextHash: HASH_B,
  parserStructureHash: HASH_C,
  importScope: "bounded_structured_docx_preview",
};

test("Office creates and saves an ACL-bound non-persisting DOCX import preview", async ({ page }, testInfo) => {
  test.setTimeout(85_000);
  await page.route("**/v1/office/documents/import-sources?**", async (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("limit")).toBe("50");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "office_import_sources.v1",
        tenant_id: "tenant-work-e2e",
        items: [{
          source_object_id: "source-docx-review",
          source_version_id: "v3",
          source_title: "Importierte DOCX-Notiz",
          updated_at_utc: "2026-10-27T08:00:00Z",
          information_classification: "confidential",
          content_byte_length: 2048,
        }],
        content_returned: false,
        current_acl_validated: true,
        audit_event_id: "audit-import-sources-review",
      }),
    });
  });
  await page.route("**/v1/office/documents/import-previews", async (route) => {
    const request = route.request(), body = request.postDataJSON();
    expect(body).toEqual({ source_object_id: "source-docx-review", source_version_id: "v3" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "office_import_preview.v2",
        tenant_id: "tenant-work-e2e",
        source_object_id: "source-docx-review",
        source_version_id: "v3",
        source_title: "Importierte DOCX-Notiz",
        source_content_hash: HASH_A,
        source_acl_version: 7,
        information_classification: "confidential",
        parser_profile_id: "rich-document-parser-worker:1",
        parser_text_hash: HASH_B,
        parser_structure_hash: HASH_C,
        warnings: ["non-executable security markers require review"],
        document: { type: "doc", attrs: { importProvenance: PROVENANCE }, content: [
          { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Sicher importierter Inhalt", marks: [{ type: "bold" }] }] },
          { type: "bulletList", content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "Struktur bleibt erhalten", marks: [{ type: "italic" }, { type: "underline" }] }] }] }] },
          { type: "pageBreak" },
          { type: "table", content: [{ type: "tableRow", content: [
            { type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "Monat" }] }] },
            { type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "Umsatz" }] }] },
          ] }] },
        ] },
        content_persisted: false,
        save_requires_explicit_confirmation: true,
        fidelity_preserved: false,
        import_scope: "bounded_structured_docx_preview",
        audit_event_id: "audit-import-preview-review",
      }),
    });
  });
  await openOffice(page);
  if (!(await page.locator("#document-import").isVisible())) await page.locator("#documents-toggle").click();
  await page.locator("#document-import").click();
  const dialog = page.locator("#import-document-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("#import-source-select")).toContainText("Importierte DOCX-Notiz");
  await dialog.getByRole("button", { name: "Sichere Vorschau erstellen" }).click();

  await expect(officeEditor(page)).toContainText("Sicher importierter Inhalt");
  await expect(page.locator("#document-mode")).toHaveText("Importvorschau");
  await expect(page.locator("#document-version")).toContainText("Quelle v3");
  await expect(page.locator("#document-classification")).toHaveValue("confidential");
  await expect(officeEditor(page).locator("h1")).toHaveText("Sicher importierter Inhalt");
  await expect(officeEditor(page).locator("ul")).toContainText("Struktur bleibt erhalten");
  await expect(officeEditor(page).locator("h1 strong")).toHaveText("Sicher importierter Inhalt");
  await expect(officeEditor(page).locator("ul em u")).toHaveText("Struktur bleibt erhalten");
  await expect(officeEditor(page).locator(".office-page-break")).toHaveCount(1);
  await expect(officeEditor(page).locator("table")).toContainText("Umsatz");
  await expect(page.locator("#document-notice")).toContainText("Strukturierte Importvorschau erstellt");

  const saved = await saveOffice(page);
  const persisted = await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id });
  expect(persisted.content.attrs.importProvenance).toEqual(PROVENANCE);
  await openOfficeDocument(page, saved.document.object_id);
  await expect(officeEditor(page)).toContainText("Sicher importierter Inhalt");
  const viewport = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth - innerWidth }));
  expect(viewport.overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-import-preview-${testInfo.project.name}.png`, fullPage: true });
});
