import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import { readdir } from "node:fs/promises";
import { resolve, relative } from "node:path";

const execFile = promisify(execFileCallback);
const desktopRoot = resolve(import.meta.dirname, "..");
const appPath = resolve(desktopRoot, "src-tauri/target/debug/bundle/macos/Lumi.app");
const verifyOnly = process.argv.includes("--verify-only");

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

async function isMachO(path) {
  const { stdout } = await execFile("file", ["-b", path]);
  return stdout.includes("Mach-O");
}

async function verify() {
  const { stderr } = await execFile("codesign", [
    "--verify",
    "--deep",
    "--strict",
    "--verbose=4",
    appPath,
  ]);
  console.log(stderr.trim() || "Strict deep code-signature verification passed.");
}

if (!verifyOnly) {
  const codeFiles = [];
  for (const path of await filesUnder(resolve(appPath, "Contents"))) {
    if (await isMachO(path)) codeFiles.push(path);
  }
  codeFiles.sort((left, right) => right.split("/").length - left.split("/").length);
  for (const path of codeFiles) {
    await execFile("codesign", [
      "--force",
      "--sign",
      "-",
      "--timestamp=none",
      path,
    ]);
    console.log(`Ad-hoc signed ${relative(appPath, path)}`);
  }
  await execFile("codesign", [
    "--force",
    "--sign",
    "-",
    "--timestamp=none",
    appPath,
  ]);
  console.log(`Ad-hoc signed ${appPath}`);
}

await verify();
