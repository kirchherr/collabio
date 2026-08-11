import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync, readlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const entries = [];
const visit = (path) => {
  const stat = lstatSync(path);
  const entry = {
    mode: stat.mode & 0o7777,
    path,
    type: stat.isDirectory() ? "directory" : stat.isSymbolicLink() ? "symlink" : "file",
  };
  if (stat.isDirectory()) {
    entries.push(entry);
    for (const child of readdirSync(path).sort()) {
      visit(join(path, child));
    }
    return;
  }
  if (stat.isSymbolicLink()) {
    entries.push({ ...entry, target: readlinkSync(path) });
    return;
  }
  if (!stat.isFile()) {
    throw new Error(`Unsupported GenOffice runtime file type: ${path}`);
  }
  const content = readFileSync(path);
  entries.push({
    ...entry,
    sha256: `sha256:${createHash("sha256").update(content).digest("hex")}`,
    size_bytes: stat.size,
  });
};

visit("/opt/genoffice");
visit("/opt/collabio/runtime-inventory.json");
writeFileSync(
  "/opt/collabio/runtime-file-inventory.json",
  `${JSON.stringify({ entries, schema_version: "genoffice_worker_runtime_file_inventory.v1" })}\n`,
  { encoding: "utf8", mode: 0o644 },
);
