import type { Map as MapLibreMap } from "maplibre-gl";

/** The pictograms fit in a square of this side, as in the Streamlit map (SIGN_ICON_PX). */
export const ICON_PX = 26;
export const ICON_PREFIX = "sign:";

// not retried: a missing file stays missing
const failed = new Set<string>();

/**
 * MapLibre can't load SVGs itself: rasterize /signs/<key>.svg on a canvas at the
 * screen's pixel ratio, keeping the pictogram's aspect (sub-panels M... are wide).
 */
async function addSignImage(map: MapLibreMap, key: string): Promise<void> {
  const id = ICON_PREFIX + key;
  if (map.hasImage(id) || failed.has(id)) return;
  try {
    const img = new Image();
    img.src = `/signs/${encodeURIComponent(key)}.svg`;
    await img.decode();

    const ratio = window.devicePixelRatio || 1;
    const aspect = img.naturalWidth && img.naturalHeight ? img.naturalWidth / img.naturalHeight : 1;
    // fit in the square: wide sub-panels get shorter
    const width = Math.round(ICON_PX * ratio * Math.min(aspect, 1));
    const height = Math.round(ICON_PX * ratio * Math.min(1 / aspect, 1));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(img, 0, 0, width, height);

    if (!map.hasImage(id)) {
      map.addImage(id, ctx.getImageData(0, 0, width, height), { pixelRatio: ratio });
    }
  } catch (error) {
    failed.add(id);
    console.warn(`Could not load the pictogram ${key}:`, error);
  }
}

/**
 * Load the pictograms before the data that uses them: MapLibre warns about every
 * image it doesn't have when it first draws a symbol.
 */
export async function loadSignImages(map: MapLibreMap, keys: Iterable<string>): Promise<void> {
  await Promise.all([...new Set(keys)].map((key) => addSignImage(map, key)));
}

const BLANK = { width: 1, height: 1, data: new Uint8Array(4) };

/** Icons the basemap's sprite lacks (OpenFreeMap: "hackerspace"...): drawn as nothing. */
export function addBlankImage(map: MapLibreMap, id: string): void {
  if (!id.startsWith(ICON_PREFIX) && !map.hasImage(id)) map.addImage(id, BLANK);
}

export const VIEW_CONE = "view-cone";
const VIEW_CONE_PX = 120; // side of the image; the camera is at its center
const VIEW_CONE_DEG = 70; // opening of the wedge

/** Orange wedge pointing north from the image center: rotated to the view bearing. */
export function addViewConeImage(map: MapLibreMap): void {
  if (map.hasImage(VIEW_CONE)) return;
  const ratio = window.devicePixelRatio || 1;
  const side = Math.round(VIEW_CONE_PX * ratio);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = side;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const c = side / 2;
  const half = (VIEW_CONE_DEG / 2) * (Math.PI / 180);
  const gradient = ctx.createRadialGradient(c, c, 0, c, c, c);
  // the current camera's color, as in the Streamlit map
  gradient.addColorStop(0, "rgba(230, 80, 40, 0.8)");
  gradient.addColorStop(1, "rgba(230, 80, 40, 0.08)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.moveTo(c, c);
  // canvas angles start east, clockwise: north is -90°
  ctx.arc(c, c, c, -Math.PI / 2 - half, -Math.PI / 2 + half);
  ctx.closePath();
  ctx.fill();
  map.addImage(VIEW_CONE, ctx.getImageData(0, 0, side, side), { pixelRatio: ratio });
}
