import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

const expected = new Map(
  Object.entries({
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
  }),
);

const raw = execFileSync(
  "npm",
  ["ls", "--json", "--all", "--omit=dev", "--ignore-scripts"],
  {
    cwd: "/opt/genoffice/packages/docx-engine",
    encoding: "utf8",
    env: { ...process.env, NPM_CONFIG_USERCONFIG: "/dev/null" },
  },
);
const tree = JSON.parse(raw);
if (tree.name !== "@genoffice/docx-engine" || tree.version !== "0.1.0") {
  throw new Error("Unexpected GenOffice DOCX engine root identity");
}
if (Array.isArray(tree.problems) && tree.problems.length > 0) {
  throw new Error(`Invalid npm runtime tree: ${tree.problems.join(", ")}`);
}

const observed = new Map();
const visit = (dependencies) => {
  for (const [name, value] of Object.entries(dependencies ?? {})) {
    if (!value || typeof value !== "object" || typeof value.version !== "string") {
      throw new Error(`Malformed npm dependency entry: ${name}`);
    }
    const versions = observed.get(name) ?? new Set();
    versions.add(value.version);
    observed.set(name, versions);
    visit(value.dependencies);
  }
};
visit(tree.dependencies);

if (observed.size !== expected.size) {
  throw new Error(`Runtime package count mismatch: expected ${expected.size}, observed ${observed.size}`);
}
for (const [name, version] of expected) {
  const versions = observed.get(name);
  if (!versions || versions.size !== 1 || !versions.has(version)) {
    throw new Error(`Runtime package mismatch: ${name}@${version}`);
  }
}
for (const name of observed.keys()) {
  if (!expected.has(name)) {
    throw new Error(`Unexpected runtime package: ${name}`);
  }
}

const inventory = {
  package_count: expected.size,
  packages: [...expected.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, version]) => ({ name, version })),
  root: { name: tree.name, version: tree.version },
  schema_version: "genoffice_worker_runtime_inventory.v1",
};
mkdirSync("/opt/collabio", { recursive: true });
writeFileSync("/opt/collabio/runtime-inventory.json", `${JSON.stringify(inventory)}\n`, {
  encoding: "utf8",
  mode: 0o644,
});
