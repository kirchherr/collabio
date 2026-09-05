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
const reviewedRuntimeDependencies = {
  "@nodable/entities": "3.0.0",
  anynum: "1.0.1",
  "core-util-is": "1.0.3",
  "fast-xml-builder": "1.3.0",
  "fast-xml-parser": "5.10.1",
  immediate: "3.0.6",
  inherits: "2.0.4",
  "is-unsafe": "2.0.0",
  isarray: "1.0.0",
  jszip: "3.10.1",
  lie: "3.3.0",
  pako: "1.0.11",
  "path-expression-matcher": "1.6.2",
  "process-nextick-args": "2.0.1",
  "readable-stream": "2.3.8",
  "safe-buffer": "5.1.2",
  setimmediate: "1.0.5",
  string_decoder: "1.1.1",
  strnum: "2.4.1",
  "util-deprecate": "1.0.2",
  "xml-naming": "0.3.0",
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

manifest.dependencies = reviewedRuntimeDependencies;
delete manifest.devDependencies;
delete manifest.scripts;
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, {
  encoding: "utf8",
  mode: 0o644,
});
