// Copies the sign pictograms of the Python app into public/signs (served at /signs/<key>.svg).
// Run before `dev` and `build`: the Python assets stay the single source of truth.
import { cpSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(web, "..", "src", "panoloc", "frontend", "assets", "signs");
const dest = join(web, "public", "signs");

if (!existsSync(src)) {
  console.error(`copy-signs: ${src} not found`);
  process.exit(1);
}
cpSync(src, dest, { recursive: true });
console.log(`copy-signs: ${src} -> ${dest}`);
