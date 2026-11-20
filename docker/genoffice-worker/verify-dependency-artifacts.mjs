import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";

const directory = "/tmp/npm-artifacts";
const report = JSON.parse(readFileSync("/tmp/dependency-report.json", "utf8"));
if (
  report.schema_version !== "genoffice_license_material_collection_report.v1" ||
  report.artifact_count !== 21 ||
  report.artifacts?.length !== 21 ||
  report.all_artifact_integrities_verified !== true ||
  report.credentials_used !== false ||
  report.lifecycle_execution_performed !== false
) {
  throw new Error("Invalid GenOffice dependency collection report");
}

const expectedNames = new Set();
for (const artifact of report.artifacts) {
  const filename = basename(artifact.artifact_filename);
  if (filename !== artifact.artifact_filename || expectedNames.has(filename)) {
    throw new Error(`Unsafe or duplicate GenOffice dependency filename: ${artifact.artifact_filename}`);
  }
  const path = join(directory, filename);
  const content = readFileSync(path);
  if (
    statSync(path).size !== artifact.size_bytes ||
    `sha256:${createHash("sha256").update(content).digest("hex")}` !== artifact.sha256 ||
    `sha512:${createHash("sha512").update(content).digest("hex")}` !== artifact.sha512 ||
    artifact.integrity_verified !== true
  ) {
    throw new Error(`GenOffice dependency integrity mismatch: ${filename}`);
  }
  expectedNames.add(filename);
}

const observedNames = readdirSync(directory)
  .filter((name) => name.endsWith(".tgz"))
  .sort();
if (
  observedNames.length !== expectedNames.size ||
  observedNames.some((name) => !expectedNames.has(name))
) {
  throw new Error("GenOffice dependency directory does not match the reviewed closure");
}
