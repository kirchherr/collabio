import { readFileSync, writeFileSync } from "node:fs";

const manifestPath = "/opt/genoffice/packages/docx-engine/package.json";
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const expectedDependencies = {
  "fast-xml-parser": "^5.3.4",
  jszip: "^3.10.1",
};
const expectedDevDependencies = {
  "@types/node": "^24.10.1",
  tsx: "^4.21.0",
  typescript: "^5.9.3",
  vitest: "^4.1.0",
};

const sameRecord = (left, right) =>
  JSON.stringify(Object.entries(left ?? {}).sort()) ===
  JSON.stringify(Object.entries(right).sort());

if (
  manifest.name !== "@genoffice/docx-engine" ||
  manifest.version !== "0.1.0" ||
  manifest.private !== true ||
  manifest.type !== "module" ||
  !sameRecord(manifest.dependencies, expectedDependencies) ||
  !sameRecord(manifest.devDependencies, expectedDevDependencies) ||
  manifest.optionalDependencies !== undefined ||
  manifest.peerDependencies !== undefined ||
  manifest.bundledDependencies !== undefined ||
  manifest.bundleDependencies !== undefined
) {
  throw new Error("GenOffice DOCX package manifest does not match the reviewed runtime boundary");
}

manifest.dependencies = {
  "fast-xml-parser": "5.10.1",
  jszip: "3.10.1",
};
delete manifest.devDependencies;
delete manifest.scripts;
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, {
  encoding: "utf8",
  mode: 0o644,
});
