import { readFile } from "node:fs/promises";
import { join } from "node:path";

let cached: Promise<Record<string, string>> | undefined;

/** Icon key -> French name of the sign, one key per file of public/signs. */
export function manifest(): Promise<Record<string, string>> {
  cached ??= readFile(join(process.cwd(), "public", "signs", "manifest.json"), "utf8").then(
    (text) => JSON.parse(text) as Record<string, string>,
  );
  return cached;
}
