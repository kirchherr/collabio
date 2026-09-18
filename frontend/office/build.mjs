import { build } from "esbuild";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

await mkdir("dist", { recursive: true });
await build({
  entryPoints: ["src/office.js"],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2022"],
  outfile: "dist/office.bundle.js",
  legalComments: "linked",
  sourcemap: false,
  metafile: true,
}).then(async (result) => {
  await writeFile("dist/build-inputs.json", JSON.stringify(result.metafile, null, 2) + "\n");
});

const lock = JSON.parse(await readFile("package-lock.json", "utf8"));
const notices = ["Collabio native Office editor — third-party notices", ""];
for (const [directory, entry] of Object.entries(lock.packages).sort(([left], [right]) => left.localeCompare(right))) {
  if (!directory || entry.dev || entry.optional) continue;
  const pkg = JSON.parse(await readFile(path.join(directory, "package.json"), "utf8"));
  if (!["MIT", "ISC", "BSD-3-Clause", "BSD-2-Clause"].includes(pkg.license)) {
    throw new Error(`Unreviewed license for ${pkg.name}: ${pkg.license}`);
  }
  let license;
  for (const file of ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "LICENSE-MIT", "LICENSE-MIT.txt"]) {
    try { license = await readFile(path.join(directory, file), "utf8"); break; } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  if (!license) throw new Error(`License text missing for ${pkg.name}`);
  notices.push(`${pkg.name}@${pkg.version} (${pkg.license})`, license, "");
}
await writeFile("dist/THIRD_PARTY_NOTICES.txt", notices.join("\n"));
