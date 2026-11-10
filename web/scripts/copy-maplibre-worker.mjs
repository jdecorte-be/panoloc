// Copies MapLibre's web worker into public/maplibre (served at /maplibre/maplibre-gl-worker.mjs).
// maplibre-gl 6 is ESM only and finds its worker next to its own module at run time:
// once bundled that file is gone, so sign-map.tsx points MapLibre here (setWorkerUrl).
// Run before `dev` and `build`: always the worker of the installed version.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
// ESM only: resolved as an import, next to its main module
const src = join(dirname(fileURLToPath(import.meta.resolve("maplibre-gl"))), "maplibre-gl-worker.mjs");
const dest = join(web, "public", "maplibre");

mkdirSync(dest, { recursive: true });
copyFileSync(src, join(dest, "maplibre-gl-worker.mjs"));
console.log(`copy-maplibre-worker: ${src} -> ${dest}`);
