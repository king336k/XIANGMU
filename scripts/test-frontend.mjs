import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";
const root = fileURLToPath(new URL("../", import.meta.url));
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}
const tests = [
  ...walk(join(root, "ProjectFront/tests")).filter((path) => path.endsWith(".mjs")),
  ...walk(join(root, "ProjectFront/core")).filter((path) => path.endsWith(".test.mjs")),
]
  .toSorted()
  .map((path) => relative(root, path));
if (!tests.length) throw new Error("没有找到前端回归检查");
const result = spawnSync(process.execPath, ["--test", ...tests], { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
